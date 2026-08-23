"""插件运行状态 —— 进程内存储，经 API 转发至插件管理页。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .util import china_now

_VALID_LEVELS = frozenset({"ok", "info", "warn", "error", "off"})


@dataclass(frozen=True)
class PluginStatus:
    level: str
    message: str
    detail: str | None = None
    updated_at: str = ""


_store: dict[str, PluginStatus] = {}


def _now_iso() -> str:
    now = china_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    if len(now) > 5 and now[-5] in "+-":
        now = f"{now[:-2]}:{now[-2:]}"
    return now


def set_status(
    plugin_id: str,
    level: str,
    message: str,
    detail: str | None = None,
) -> None:
    """写入插件运行状态（level: ok / info / warn / error / off）。"""
    lv = str(level or "info").lower()
    if lv not in _VALID_LEVELS:
        lv = "info"
    msg = str(message or "").strip()
    if not msg:
        msg = lv
    det = str(detail).strip() if detail else None
    _store[str(plugin_id)] = PluginStatus(
        level=lv,
        message=msg,
        detail=det,
        updated_at=_now_iso(),
    )


def get_status(plugin_id: str) -> PluginStatus | None:
    return _store.get(str(plugin_id))


def to_dict(st: PluginStatus) -> dict[str, Any]:
    out: dict[str, Any] = {
        "level": st.level,
        "message": st.message,
        "updated_at": st.updated_at,
    }
    if st.detail:
        out["detail"] = st.detail
    return out


def resolve_runtime_status(
    plugin_id: str,
    *,
    enabled: bool,
    file_exists: bool,
    loaded: bool,
) -> dict[str, Any]:
    """按注册表与加载结果合成最终展示状态。"""
    if not enabled:
        return to_dict(PluginStatus("off", "已停用", updated_at=_now_iso()))
    if not file_exists:
        return to_dict(PluginStatus("error", "插件文件不存在", updated_at=_now_iso()))
    if not loaded:
        st = get_status(plugin_id)
        if st:
            return to_dict(st)
        return to_dict(
            PluginStatus(
                "error",
                "未加载",
                detail="请重启 server；若仍失败请查看后端日志",
                updated_at=_now_iso(),
            )
        )
    st = get_status(plugin_id)
    if st:
        return to_dict(st)
    return to_dict(PluginStatus("ok", "已加载", updated_at=_now_iso()))
