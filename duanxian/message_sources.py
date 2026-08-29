"""插件消息源进程内注册表 —— 不落库，停用插件即清除。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .util import china_now

# 内置 / 系统占用的 source_id，插件不可注册
RESERVED_SOURCE_IDS: frozenset[str] = frozenset({
    "manual",
    "article",
    "calendar",
    "cls_telegraph",
    "xgb_msgs",
})

_LOCK = threading.Lock()
_SOURCES: dict[str, "PluginMessageSource"] = {}


@dataclass(frozen=True)
class PluginMessageSource:
    source_id: str
    plugin_id: str
    label: str
    registered_at: str


def register(plugin_id: str, source_id: str, label: str = "") -> PluginMessageSource:
    """登记插件消息源；同插件可重复注册以更新 label。"""
    pid = str(plugin_id or "").strip()
    sid = str(source_id or "").strip()
    if not pid:
        raise ValueError("plugin_id 不能为空")
    if not sid:
        raise ValueError("source_id 不能为空")
    if sid in RESERVED_SOURCE_IDS:
        raise ValueError(f"source_id {sid!r} 为系统保留，不可由插件注册")
    lbl = (label or "").strip() or sid
    now = china_now().strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        existing = _SOURCES.get(sid)
        if existing is not None and existing.plugin_id != pid:
            raise ValueError(
                f"source_id {sid!r} 已被插件 {existing.plugin_id} 注册"
            )
        rec = PluginMessageSource(
            source_id=sid,
            plugin_id=pid,
            label=lbl,
            registered_at=existing.registered_at if existing else now,
        )
        _SOURCES[sid] = rec
        return rec


def unregister_plugin(plugin_id: str) -> int:
    """清除某插件登记的全部消息源，返回清除条数。"""
    pid = str(plugin_id or "").strip()
    if not pid:
        return 0
    with _LOCK:
        to_drop = [sid for sid, rec in _SOURCES.items() if rec.plugin_id == pid]
        for sid in to_drop:
            del _SOURCES[sid]
        return len(to_drop)


def get(source_id: str) -> PluginMessageSource | None:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        return _SOURCES.get(sid)


def require_owned(source_id: str, plugin_id: str) -> PluginMessageSource:
    """校验 source_id 已注册且归属当前插件。"""
    rec = get(source_id)
    if rec is None:
        raise ValueError(f"消息源 {source_id!r} 未注册")
    if rec.plugin_id != str(plugin_id):
        raise ValueError(f"消息源 {source_id!r} 不属于当前插件")
    return rec


def list_registered() -> list[PluginMessageSource]:
    with _LOCK:
        return sorted(_SOURCES.values(), key=lambda r: r.source_id)


def clear_all() -> None:
    """测试用：清空注册表。"""
    with _LOCK:
        _SOURCES.clear()


def as_source_info_dicts() -> list[dict[str, Any]]:
    """供 list_sources 合并的 MessageSourceInfo 形状 dict。"""
    return [
        {
            "id": r.source_id,
            "label": r.label,
            "adapter_type": "plugin",
            "enabled": True,
            "poll_interval_s": None,
            "last_poll_at": None,
            "last_error": None,
        }
        for r in list_registered()
    ]
