"""题材标签归一 —— 统计涨停事件数时把等价写法合并到同一 canonical 名。

只走**显式别名表**，不做 token 替换或语义相似度合并。
配置落盘：`~/.duanxian-agents/config/theme_aliases.json`
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from .util import atomic_write_json

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "theme_aliases.json")
_SCHEMA = 1
_MAX_LEN = 20
_LOCK = threading.Lock()

# 内置默认：仅收录已确认等价的写法
_DEFAULT_ALIASES: dict[str, str] = {
    "半年报增长": "中报增长",
    "半年报预增": "中报增长",
    "中报预增": "中报增长",
    "人形机器人": "机器人",
}

_ALIASES: dict[str, str] | None = None


class ThemeAliasError(ValueError):
    """题材别名配置非法。"""


def _norm_tag(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def default_aliases() -> dict[str, str]:
    return dict(_DEFAULT_ALIASES)


def _read_disk() -> dict[str, str]:
    if not os.path.isfile(_CONFIG_PATH):
        return default_aliases()
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return default_aliases()
        raw = env.get("aliases")
        if not isinstance(raw, dict):
            return default_aliases()
        out: dict[str, str] = {}
        for alias, canonical in raw.items():
            a, c = _norm_tag(alias), _norm_tag(canonical)
            if a and c and a != c:
                out[a] = c
        return out or default_aliases()
    except Exception:  # noqa: BLE001
        return default_aliases()


def _assert_no_cycles(aliases: dict[str, str]) -> None:
    for start in aliases:
        seen = {start}
        cur = aliases[start]
        while cur in aliases:
            if cur in seen:
                raise ThemeAliasError(f"题材别名存在环：{start}")
            seen.add(cur)
            cur = aliases[cur]


def _sanitize_aliases(aliases: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for alias, canonical in (aliases or {}).items():
        a, c = _norm_tag(alias), _norm_tag(canonical)
        if not a or not c:
            raise ThemeAliasError("别名与标准题材均不能为空")
        if a == c:
            raise ThemeAliasError(f"别名与标准题材不能相同：{a}")
        if len(a) > _MAX_LEN or len(c) > _MAX_LEN:
            raise ThemeAliasError(f"题材名不超过 {_MAX_LEN} 个字")
        out[a] = c
    _assert_no_cycles(out)
    return out


def load_aliases() -> dict[str, str]:
    """读取当前别名表（带进程内缓存）。"""
    global _ALIASES
    if _ALIASES is not None:
        return dict(_ALIASES)
    with _LOCK:
        if _ALIASES is None:
            _ALIASES = _read_disk()
        return dict(_ALIASES)


def reload_aliases() -> dict[str, str]:
    """丢弃缓存并重新读盘。"""
    global _ALIASES
    with _LOCK:
        _ALIASES = _read_disk()
        return dict(_ALIASES)


def save_aliases(aliases: dict[str, str]) -> dict[str, str]:
    """校验并写入别名表，返回清洗后的副本。"""
    cleaned = _sanitize_aliases(aliases)
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "aliases": cleaned}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入题材别名配置失败：{_CONFIG_PATH}")
    global _ALIASES
    with _LOCK:
        _ALIASES = dict(cleaned)
    return dict(cleaned)


def reset_aliases() -> dict[str, str]:
    """恢复内置默认别名表。"""
    return save_aliases(default_aliases())


def export_config() -> dict:
    """供 API / 设置页读取。"""
    aliases = load_aliases()
    return {
        "schema": _SCHEMA,
        "aliases": aliases,
        "entries": [{"alias": a, "canonical": c} for a, c in sorted(aliases.items())],
        "path": _CONFIG_PATH,
        "defaults": default_aliases(),
    }


def canonicalize_tag(tag: str, aliases: Optional[dict[str, str]] = None) -> str:
    """把单个题材标签映射到 canonical 名；未命中则原样返回。"""
    t = _norm_tag(tag)
    if not t:
        return t
    mapping = aliases if aliases is not None else load_aliases()
    seen = {t}
    while t in mapping:
        nxt = mapping[t]
        if nxt in seen:
            break
        seen.add(nxt)
        t = nxt
    return t
