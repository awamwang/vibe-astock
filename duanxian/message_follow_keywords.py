"""消息关注词 —— 消息分析命中筛选。

配置落盘：`~/.duanxian-agents/config/message_follow_keywords.json`
无内置默认词，由用户在自定义配置页维护。
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
_MAX_LEN = 20
_LOCK = threading.Lock()
_KEYWORDS: list[str] | None = None


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "message_follow_keywords.json")


class MessageFollowKeywordError(ValueError):
    """消息关注词配置非法。"""


def _norm_tag(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def _sanitize(keywords: object) -> list[str]:
    if not isinstance(keywords, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in keywords:
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
        return _sanitize(env.get("keywords"))
    except Exception:  # noqa: BLE001
        return []


def load_keywords() -> list[str]:
    """读取当前关注词列表（带进程内缓存）。"""
    global _KEYWORDS
    if _KEYWORDS is not None:
        return list(_KEYWORDS)
    with _LOCK:
        if _KEYWORDS is None:
            _KEYWORDS = _read_disk()
        return list(_KEYWORDS)


def reload_keywords() -> list[str]:
    """丢弃缓存并重新读盘。"""
    global _KEYWORDS
    with _LOCK:
        _KEYWORDS = _read_disk()
        return list(_KEYWORDS)


def save_keywords(keywords: list) -> list[str]:
    """校验并写入关注词列表，返回清洗后的副本。"""
    cleaned = _sanitize(keywords)
    for tag in cleaned:
        if len(tag) > _MAX_LEN:
            raise MessageFollowKeywordError(f"关注词不超过 {_MAX_LEN} 个字：{tag}")
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "keywords": cleaned}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入消息关注词配置失败：{_CONFIG_PATH}")
    global _KEYWORDS
    with _LOCK:
        _KEYWORDS = list(cleaned)
    return list(cleaned)


def reset_keywords() -> list[str]:
    """清空关注词列表。"""
    return save_keywords([])


def export_config() -> dict:
    """供 API / 设置页读取。"""
    keywords = load_keywords()
    return {
        "schema": _SCHEMA,
        "keywords": keywords,
        "path": _CONFIG_PATH,
    }


def match_in_text(keywords: list[str], title: str, summary: str, detail: str, msg_keywords: list[str]) -> list[str]:
    """在消息文本中查找命中的关注词，返回命中列表（保持配置顺序）。"""
    if not keywords:
        return []
    haystack = "\n".join(
        [
            title or "",
            summary or "",
            detail or "",
            " ".join(str(k) for k in (msg_keywords or [])),
        ]
    )
    return [kw for kw in keywords if kw and kw in haystack]


def build_follow_sql(keywords: list[str]) -> tuple[str, list[str]]:
    """生成「命中任一关注词」的 SQL 片段与参数。"""
    if not keywords:
        return "1=0", []
    parts: list[str] = []
    args: list[str] = []
    for kw in keywords:
        like = f"%{kw}%"
        parts.append("(title LIKE ? OR summary LIKE ? OR detail LIKE ? OR keywords_json LIKE ?)")
        args.extend([like, like, like, like])
    return f"({' OR '.join(parts)})", args
