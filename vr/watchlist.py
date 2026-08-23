"""自选股数据层 —— 用户或插件写入的标的列表，存本地 ~/.vibe-research/watchlist.json。

与前端 localStorage 可经 /api/watchlist 同步；插件经 HookRegistry.import_watchlist 全量覆盖。
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vibe-research")
WL_FILE = os.path.join(CACHE_DIR, "watchlist.json")
_SCHEMA = 1
_MAX_CODES = 100
_CODE_RE = re.compile(r"^\d{6}$")
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")


def _default() -> dict:
    return {"schema": _SCHEMA, "codes": [], "updated_at": None}


def _load() -> dict:
    try:
        with open(WL_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _default()
        codes = data.get("codes")
        if not isinstance(codes, list):
            return _default()
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default()


def _save(data: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = WL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, WL_FILE)


def normalize_codes(codes: Any) -> list[str]:
    """校验并去重，最多保留 _MAX_CODES 只。"""
    if codes is None:
        return []
    if isinstance(codes, str):
        codes = [c.strip() for c in codes.split(",") if c.strip()]
    if not isinstance(codes, list):
        raise ValueError("codes 须为字符串数组")
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        c = str(raw or "").strip()
        if not _CODE_RE.match(c) or c in seen:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= _MAX_CODES:
            break
    return out


def replace_codes(codes: Any) -> dict:
    """全量覆盖自选股列表。"""
    clean = normalize_codes(codes)
    with _LOCK:
        data = _load()
        data["schema"] = _SCHEMA
        data["codes"] = clean
        data["updated_at"] = _now()
        _save(data)
    return get_watchlist()


def get_codes() -> list[str]:
    with _LOCK:
        return list(_load().get("codes") or [])


def get_watchlist() -> dict:
    with _LOCK:
        data = _load()
    return {
        "schema": _SCHEMA,
        "codes": list(data.get("codes") or []),
        "updated_at": data.get("updated_at"),
    }
