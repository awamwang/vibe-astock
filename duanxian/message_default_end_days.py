"""消息默认有效期（天）—— 未设 end_at 时按生效时间 + N 天计算。

配置落盘：`~/.duanxian-agents/config/message_default_end_days.json`
"""

from __future__ import annotations

import json
import os
import threading

from .util import atomic_write_json

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "message_default_end_days.json")
_SCHEMA = 1
_DEFAULT_DAYS = 5
_MIN_DAYS = 1
_MAX_DAYS = 15
_LOCK = threading.Lock()
_DAYS: int | None = None


class MessageDefaultEndDaysError(ValueError):
    """默认有效期配置非法。"""


def clamp_days(raw: object) -> int:
    """清洗为 1–15 的整数；非法时回退默认。"""
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_DAYS
    return max(_MIN_DAYS, min(_MAX_DAYS, n))


def _read_disk() -> tuple[int, bool]:
    """返回 (天数, 是否来自磁盘文件)。"""
    if not os.path.isfile(_CONFIG_PATH):
        return _DEFAULT_DAYS, False
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return _DEFAULT_DAYS, True
        return clamp_days(env.get("default_end_days", _DEFAULT_DAYS)), True
    except Exception:  # noqa: BLE001
        return _DEFAULT_DAYS, True


def load_days() -> int:
    """读取当前默认有效期（带进程内缓存）。"""
    global _DAYS
    if _DAYS is not None:
        return int(_DAYS)
    with _LOCK:
        if _DAYS is None:
            _DAYS, _ = _read_disk()
        return int(_DAYS)


def reload_days() -> int:
    """丢弃缓存并重新读盘。"""
    global _DAYS
    with _LOCK:
        _DAYS, _ = _read_disk()
        return int(_DAYS)


def save_days(days: object) -> int:
    """校验并写入默认有效期，返回清洗后的值。"""
    try:
        n = int(days)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MessageDefaultEndDaysError("默认有效期须为整数") from exc
    if n < _MIN_DAYS or n > _MAX_DAYS:
        raise MessageDefaultEndDaysError(f"默认有效期须在 {_MIN_DAYS}–{_MAX_DAYS} 天")
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "default_end_days": n}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入消息默认有效期配置失败：{_CONFIG_PATH}")
    global _DAYS
    with _LOCK:
        _DAYS = n
    return n


def reset_days() -> int:
    """恢复内置默认（5 天）并写盘。"""
    return save_days(_DEFAULT_DAYS)


def export_config() -> dict:
    """供 API / 前端读取。"""
    days, from_disk = _read_disk()
    # 与缓存对齐
    global _DAYS
    with _LOCK:
        _DAYS = days
    return {
        "schema": _SCHEMA,
        "default_end_days": days,
        "min": _MIN_DAYS,
        "max": _MAX_DAYS,
        "from_disk": from_disk,
        "path": _CONFIG_PATH,
    }
