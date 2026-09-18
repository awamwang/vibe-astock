"""收盘后探测定稿短线并推送到飞书：每个交易日只推一次。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from duanxian.trade_calendar import is_settled
from duanxian.util import china_now, china_today

from .page import handle_push, im_gaps, push_gaps

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 30.0
SETTLED_NOTICE = "今日短线盘面数据已更新"
PUSHED_AT_FMT = "%Y-%m-%d %H:%M:%S"
# 短线盘面一行依赖的、会在收盘后落盘 ``settled: true`` 的数据源。
REQUIRED_SETTLED_SOURCES = ("short_board", "live_emotion", "live_zt_effect")

_ACTIVE: SettledPushPoller | None = None


def default_state_path() -> Path:
    return Path.home() / ".vibe-astock" / "lark-stock-settled-push.json"


def _source_data(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, dict):
        return None
    wrap = sources.get(key)
    if not isinstance(wrap, dict) or not wrap.get("available"):
        return None
    data = wrap.get("data")
    return data if isinstance(data, dict) else None


def payload_all_settled(payload: dict[str, Any], today: str) -> bool:
    """今日短线相关源是否都已带上收盘定稿标记。"""
    if not isinstance(payload, dict):
        return False
    if str(payload.get("date") or "").strip() != today:
        return False
    for key in REQUIRED_SETTLED_SOURCES:
        data = _source_data(payload, key)
        if data is None:
            return False
        if data.get("settled") is not True:
            return False
        src_date = str(data.get("date") or "").strip()
        if src_date and src_date != today:
            return False
    return True


def now_pushed_at() -> str:
    return china_now().strftime(PUSHED_AT_FMT)


def _empty_state() -> dict[str, str]:
    return {"pushed_date": "", "notified_date": "", "pushed_at": ""}


def load_state(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    return {
        "pushed_date": str(raw.get("pushed_date") or "").strip(),
        "notified_date": str(raw.get("notified_date") or "").strip(),
        "pushed_at": str(raw.get("pushed_at") or "").strip(),
    }


def save_state(
    path: Path,
    pushed_date: str,
    notified_date: str,
    pushed_at: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pushed_date": pushed_date,
        "notified_date": notified_date,
        "pushed_at": pushed_at,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def last_push_at() -> str:
    """供插件页读取上次成功推送时间。优先内存，否则读落盘。"""
    poller = _ACTIVE
    if poller is not None:
        return poller.last_pushed_at()
    return load_state(default_state_path())["pushed_at"]


def record_push_success(at: str | None = None) -> str:
    """表格推送成功后记下时间；自动定稿与手动推送共用。"""
    stamp = (at or now_pushed_at()).strip()
    poller = _ACTIVE
    if poller is not None:
        poller.note_pushed_at(stamp)
        return stamp
    saved = load_state(default_state_path())
    save_state(
        default_state_path(),
        saved["pushed_date"],
        saved["notified_date"],
        stamp,
    )
    return stamp


class SettledPushPoller:
    """收盘后每 30 秒探测短线定稿；齐了就推送表格并通知群聊，每日一次。"""

    def __init__(
        self,
        *,
        service: Any,
        plugin_id: str,
        fetch_live: Callable[[], dict[str, Any]],
        registry: Any | None = None,
        state_path: Path | None = None,
        interval: float = POLL_INTERVAL_SEC,
        notice: str = SETTLED_NOTICE,
    ) -> None:
        self._service = service
        self._plugin_id = plugin_id
        self._fetch_live = fetch_live
        self._registry = registry
        self._state_path = state_path or default_state_path()
        self._interval = max(1.0, float(interval))
        self._notice = notice
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        saved = load_state(self._state_path)
        self._pushed_date = saved["pushed_date"]
        self._notified_date = saved["notified_date"]
        self._pushed_at = saved["pushed_at"]

    def start(self) -> None:
        global _ACTIVE
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="lark-stock-settled-push",
            daemon=True,
        )
        self._thread.start()
        _ACTIVE = self
        logger.info("短线定稿推送已启动，收盘后每 %.0f 秒探测一次", self._interval)

    def stop(self) -> None:
        global _ACTIVE
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None
        if _ACTIVE is self:
            _ACTIVE = None

    def last_pushed_at(self) -> str:
        with self._state_lock:
            return self._pushed_at

    def note_pushed_at(self, at: str) -> None:
        self._remember(pushed_at=str(at or "").strip())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("短线定稿推送探测失败")
                self._report("warn", "短线定稿推送探测失败")
            self._stop.wait(self._interval)

    def _snapshot_state(self) -> tuple[str, str]:
        with self._state_lock:
            return self._pushed_date, self._notified_date

    def _remember(
        self,
        *,
        pushed_date: str | None = None,
        notified_date: str | None = None,
        pushed_at: str | None = None,
    ) -> None:
        with self._state_lock:
            if pushed_date is not None:
                self._pushed_date = pushed_date
            if notified_date is not None:
                self._notified_date = notified_date
            if pushed_at is not None:
                self._pushed_at = pushed_at
            pushed = self._pushed_date
            notified = self._notified_date
            at = self._pushed_at
        try:
            save_state(self._state_path, pushed, notified, at)
        except OSError:
            logger.exception("短线定稿推送状态未能落盘")

    def _bind(self) -> None:
        reg = self._registry
        if reg is None:
            return
        pid = self._plugin_id
        if pid:
            reg.bind_plugin(pid)

    def _report(self, level: str, message: str, detail: str | None = None) -> None:
        reg = self._registry
        if reg is None:
            return
        try:
            self._bind()
            reg.report_status(level, message, detail)
        except Exception:
            logger.debug("上报插件状态失败", exc_info=True)

    def tick(self) -> str:
        """探测一次。返回动作名，便于测试。"""
        if self._stop.is_set():
            return "stopped"
        today = china_today()
        if not is_settled(today):
            return "skip_window"
        pushed, notified = self._snapshot_state()
        if pushed == today and notified == today:
            return "skip_done"
        service = self._service
        if service is None:
            return "skip_service"
        gaps = push_gaps(service.config)
        if gaps:
            self._report("warn", "定稿推送缺少配置", "、".join(label for _, label in gaps))
            return "skip_config"

        if pushed != today:
            try:
                payload = self._fetch_live()
            except Exception as exc:
                logger.warning("读取短线钩子失败：%s", exc)
                self._report("warn", "读取短线钩子失败", str(exc))
                return "fetch_error"
            if not payload_all_settled(payload, today):
                self._report("ok", "收盘后等待短线定稿")
                return "wait_settle"
            result = handle_push(
                service,
                self._plugin_id,
                fetch_live=lambda: payload,
            )
            if not result.get("ok"):
                err = str(result.get("error") or "推送失败")
                logger.warning("定稿短线推送失败：%s", err)
                self._report("warn", "定稿短线推送失败", err)
                return "push_error"
            self._remember(pushed_date=today, pushed_at=now_pushed_at())
            logger.info("已推送 %s 定稿短线盘面", today)

        if self._stop.is_set():
            return "pushed"
        pushed, notified = self._snapshot_state()
        if notified == today:
            return "skip_done"
        if im_gaps(service.config):
            self._remember(notified_date=today)
            self._report("ok", "已推送今日定稿短线（未配置消息接收方）")
            return "pushed_no_im"
        try:
            service.messenger.send_text(self._notice)
        except Exception as exc:
            logger.warning("定稿短线已推送，群消息发送失败：%s", exc)
            self._report("warn", "定稿短线已推送，群消息发送失败", str(exc))
            return "notify_error"
        self._remember(notified_date=today)
        self._report("ok", "已推送今日定稿短线并通知群聊")
        logger.info("已通知群聊：%s", self._notice)
        return "pushed"
