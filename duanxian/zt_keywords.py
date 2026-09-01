"""上涨/涨停原因关键词 —— 首板深入分析闭集标签。

配置落盘：`~/.duanxian-agents/config/zt_keywords.json`
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
_LOCKED = ("无原因", "其他")
_DEFAULT: list[str] = [
    "并购", "重组", "涨价", "借壳", "业绩", "政策", "创新", "增持",
    "高送转", "次新", "国际局势", "自然", "订单", "无原因", "其他",
]
_LOCK = threading.Lock()
_KEYWORDS: list[str] | None = None


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "zt_keywords.json")


class ZtKeywordError(ValueError):
    """上涨关键词配置非法。"""


def _norm_tag(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def default_keywords() -> list[str]:
    return list(_DEFAULT)


def locked_keywords() -> list[str]:
    return list(_LOCKED)


def _sanitize(keywords: object) -> list[str]:
    if not isinstance(keywords, list):
        return default_keywords()
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
    for locked in _LOCKED:
        if locked not in seen:
            out.append(locked)
            seen.add(locked)
    return out if out else default_keywords()


def _read_disk() -> list[str]:
    if not os.path.isfile(_CONFIG_PATH):
        return default_keywords()
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return default_keywords()
        raw = env.get("keywords")
        return _sanitize(raw)
    except Exception:  # noqa: BLE001
        return default_keywords()


def load_keywords() -> list[str]:
    """读取当前关键词列表（带进程内缓存）。"""
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
    """校验并写入关键词列表，返回清洗后的副本。"""
    cleaned = _sanitize(keywords)
    for tag in cleaned:
        if len(tag) > _MAX_LEN:
            raise ZtKeywordError(f"标签不超过 {_MAX_LEN} 个字：{tag}")
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "keywords": cleaned}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入上涨关键词配置失败：{_CONFIG_PATH}")
    global _KEYWORDS
    with _LOCK:
        _KEYWORDS = list(cleaned)
    return list(cleaned)


def reset_keywords() -> list[str]:
    """恢复内置默认关键词列表。"""
    return save_keywords(default_keywords())


def export_config() -> dict:
    """供 API / 设置页读取。"""
    keywords = load_keywords()
    return {
        "schema": _SCHEMA,
        "keywords": keywords,
        "locked": locked_keywords(),
        "path": _CONFIG_PATH,
        "defaults": default_keywords(),
    }
