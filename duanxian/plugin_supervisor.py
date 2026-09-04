"""插件运行监督：检测报错/未加载，按指数退避自动热重启。

默认开启；设环境变量 ``VIBE_PLUGIN_SUPERVISOR=0`` 可关闭。
间隔：``VIBE_PLUGIN_RETRY_BASE_SEC``（默认 5）起，按 2^n 增长，
上限 ``VIBE_PLUGIN_RETRY_MAX_SEC``（默认 300）；轮询 ``VIBE_PLUGIN_SUPERVISOR_POLL_SEC``（默认 2）。
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import dataclass


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class _RetryState:
    attempt: int = 0
    next_at: float = 0.0
    in_flight: bool = False
    base_message: str = ""


_lock = threading.Lock()
_states: dict[str, _RetryState] = {}
_started = False
_stop = threading.Event()
_thread: threading.Thread | None = None
# 按需 nudge 限流：同一插件最短间隔（秒）
_NUDGE_MIN_INTERVAL = 3.0
_last_nudge_at: dict[str, float] = {}


def _is_unhealthy(plugin_id: str, *, enabled: bool, loaded: bool) -> bool:
    """已启用但加载失败或运行状态为 error 时视为不健康。"""
    if not enabled:
        return False
    from . import plugin_status as ps

    st = ps.get_status(plugin_id)
    if st is not None and st.level == "error":
        return True
    if not loaded:
        # 启用却未进 PLUGINS：通常是启动加载失败
        return True
    return False


def _is_healthy(plugin_id: str, *, enabled: bool, loaded: bool) -> bool:
    if not enabled:
        return True
    from . import plugin_status as ps

    st = ps.get_status(plugin_id)
    if not loaded:
        return False
    if st is None:
        return True
    return st.level in ("ok", "info", "warn")


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    # attempt 从 0 起：5, 10, 20, … 直至 cap
    exp = max(0, int(attempt))
    return min(cap, base * (2**exp))


def _annotate_waiting(plugin_id: str, state: _RetryState, wait_sec: float) -> None:
    from . import plugin_status as ps

    st = ps.get_status(plugin_id)
    base = state.base_message
    if not base and st is not None:
        base = st.message
        # 去掉此前附加的倒计时后缀，避免叠写
        if " · " in base and "后自动重启" in base:
            base = base.split(" · ", 1)[0]
        state.base_message = base
    if not base:
        base = "运行异常"
        state.base_message = base
    wait_i = max(1, int(wait_sec + 0.999))
    msg = f"{base} · {wait_i}s 后自动重启（第 {state.attempt + 1} 次）"
    detail = st.detail if st is not None else None
    ps.set_status(plugin_id, "error", msg, detail)


def _clear_state(plugin_id: str) -> None:
    with _lock:
        _states.pop(plugin_id, None)


def _tick(*, now: float | None = None) -> None:
    from . import plugin_status as ps
    from . import plugin_store as pstore
    from . import hooks

    now = time.monotonic() if now is None else now
    base = max(0.5, _env_float("VIBE_PLUGIN_RETRY_BASE_SEC", 5.0))
    cap = max(base, _env_float("VIBE_PLUGIN_RETRY_MAX_SEC", 300.0))

    loaded_ids = {lp.id for lp in hooks.PLUGINS}
    for rec in pstore.list_plugins():
        pid = rec.id
        if not rec.enabled:
            _clear_state(pid)
            continue

        loaded = pid in loaded_ids
        if _is_healthy(pid, enabled=True, loaded=loaded):
            _clear_state(pid)
            continue

        if not _is_unhealthy(pid, enabled=True, loaded=loaded):
            continue

        with _lock:
            state = _states.get(pid)
            if state is None:
                state = _RetryState(attempt=0, next_at=now + base)
                st0 = ps.get_status(pid)
                if st0 is not None:
                    state.base_message = st0.message
                _states[pid] = state
            if state.in_flight:
                continue
            wait = state.next_at - now
            if wait > 0:
                _annotate_waiting(pid, state, wait)
                continue
            state.in_flight = True
            attempt = state.attempt

        try:
            print(
                f"ℹ️ 插件监督：自动重启 id={pid}（第 {attempt + 1} 次，"
                f"退避上限 {cap:.0f}s）"
            )
            hooks.apply_plugin_restart(pid)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            loaded_ids = {lp.id for lp in hooks.PLUGINS}
            still_bad = _is_unhealthy(pid, enabled=True, loaded=pid in loaded_ids)
            with _lock:
                state = _states.get(pid)
                if state is None:
                    continue
                state.in_flight = False
                if still_bad:
                    state.attempt = attempt + 1
                    delay = _backoff_delay(state.attempt, base, cap)
                    state.next_at = time.monotonic() + delay
                    st1 = ps.get_status(pid)
                    if st1 is not None and st1.level == "error":
                        # 保留重启后插件写入的报错文案作为下次倒计时基底
                        raw = st1.message
                        if " · " in raw and "后自动重启" in raw:
                            raw = raw.split(" · ", 1)[0]
                        state.base_message = raw
                    _annotate_waiting(pid, state, delay)
                else:
                    _states.pop(pid, None)


def _loop() -> None:
    from . import hooks

    hooks._plugins_init_done.wait(timeout=180.0)
    poll = max(0.5, _env_float("VIBE_PLUGIN_SUPERVISOR_POLL_SEC", 2.0))
    while not _stop.is_set():
        if not _env_flag("VIBE_PLUGIN_SUPERVISOR", True):
            _stop.wait(poll)
            continue
        try:
            _tick()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _stop.wait(poll)


def ensure_started() -> None:
    """启动监督守护线程（幂等）。"""
    global _started, _thread
    with _lock:
        if _started:
            return
        if not _env_flag("VIBE_PLUGIN_SUPERVISOR", True):
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop,
            name="plugin-supervisor",
            daemon=True,
        )
        _thread.start()
        _started = True


def nudge(*, plugin_id: str | None = None) -> list[str]:
    """按需加速恢复：跳过剩余退避，立刻尝试重启不健康插件。

    供个股联动、插件列表等功能路径调用；带最短间隔限流，避免轮询风暴。
    与后台轮询开关无关：即使 ``VIBE_PLUGIN_SUPERVISOR=0`` 仍可按需触发。
    返回本次被提前调度的 plugin_id 列表。
    """
    from . import plugin_store as pstore
    from . import hooks

    now = time.monotonic()
    loaded_ids = {lp.id for lp in hooks.PLUGINS}
    nudged: list[str] = []

    for rec in pstore.list_plugins():
        pid = rec.id
        if plugin_id is not None and pid != plugin_id:
            continue
        if not rec.enabled:
            continue
        loaded = pid in loaded_ids
        if not _is_unhealthy(pid, enabled=True, loaded=loaded):
            continue

        with _lock:
            last = _last_nudge_at.get(pid, 0.0)
            if now - last < _NUDGE_MIN_INTERVAL:
                continue
            _last_nudge_at[pid] = now
            state = _states.get(pid)
            if state is None:
                state = _RetryState(attempt=0, next_at=now)
                from . import plugin_status as ps

                st0 = ps.get_status(pid)
                if st0 is not None:
                    state.base_message = st0.message
                _states[pid] = state
            elif not state.in_flight:
                state.next_at = now
            nudged.append(pid)

    if nudged:
        try:
            _tick(now=now)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return nudged


def ensure_plugins_ready(*, plugin_id: str | None = None) -> None:
    """功能路径按需恢复：先唤起插件自愈钩子，再 nudge 监督线程。

    插件模块若导出 ``ensure_bridge_alive`` / ``ensure_alive``，在 warn/未就绪时
    可打断自身重连退避；对真正的 error/未加载仍走监督热重启。
    """
    from . import hooks

    hooks.invoke_plugin_ensure_alive(plugin_id=plugin_id)
    nudge(plugin_id=plugin_id)


def stop_for_tests() -> None:
    """测试用：停止监督线程并清空退避状态。"""
    global _started, _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
    with _lock:
        _states.clear()
        _last_nudge_at.clear()
        _started = False
        _thread = None


def reset_state_for_tests() -> None:
    """测试用：仅清空退避状态，不杀线程。"""
    with _lock:
        _states.clear()
        _last_nudge_at.clear()
