"""自定义消息标记 —— 个股日记快捷标题。

配置落盘：`~/.duanxian-agents/config/message_manual_marks.json`
无内置默认项，由用户在自定义配置页维护；单条不超过 10 个字。
"""

from __future__ import annotations

import json
import os
import threading

from . import paths as _paths
from .util import atomic_write_json

_CONFIG_DIR = ""
_CONFIG_PATH = ""
_SCHEMA = 1
_MAX_LEN = 10
_LOCK = threading.Lock()
_MARKS: list[str] | None = None


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "message_manual_marks.json")


class MessageManualMarkError(ValueError):
    """自定义消息标记配置非法。"""


def _norm_tag(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def _sanitize(marks: object) -> list[str]:
    if not isinstance(marks, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in marks:
        if not isinstance(item, str):
            continue
        t = _norm_tag(item)
        if not t or len(t) > _MAX_LEN or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _read_disk() -> list[str]:
    if not os.path.isfile(_CONFIG_PATH):
        return []
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return []
        return _sanitize(env.get("marks") if "marks" in env else env.get("keywords"))
    except Exception:  # noqa: BLE001
        return []


def load_marks() -> list[str]:
    """读取当前标记列表（带进程内缓存）。"""
    global _MARKS
    if _MARKS is not None:
        return list(_MARKS)
    with _LOCK:
        if _MARKS is None:
            _MARKS = _read_disk()
        return list(_MARKS)


def reload_marks() -> list[str]:
    """丢弃缓存并重新读盘。"""
    global _MARKS
    with _LOCK:
        _MARKS = _read_disk()
        return list(_MARKS)


def save_marks(marks: list) -> list[str]:
    """校验并写入标记列表，返回清洗后的副本。"""
    cleaned = _sanitize(marks)
    for tag in cleaned:
        if len(tag) > _MAX_LEN:
            raise MessageManualMarkError(f"标记不超过 {_MAX_LEN} 个字：{tag}")
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "marks": cleaned}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入自定义消息标记配置失败：{_CONFIG_PATH}")
    global _MARKS
    with _LOCK:
        _MARKS = list(cleaned)
    return list(cleaned)


def reset_marks() -> list[str]:
    """清空标记列表。"""
    return save_marks([])


def export_config() -> dict:
    """供 API / 设置页读取。"""
    marks = load_marks()
    return {
        "schema": _SCHEMA,
        "marks": marks,
        "max_len": _MAX_LEN,
        "path": _CONFIG_PATH,
    }
