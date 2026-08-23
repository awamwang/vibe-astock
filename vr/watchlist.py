"""自选股数据层 —— 用户或插件写入的标的列表，存本地 ~/.vibe-research/watchlist.json。

与前端 localStorage 可经 /api/watchlist 同步；插件经 HookRegistry.import_watchlist 合并或覆盖。
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
SOURCE_MANUAL = "手动添加"
BEIJING = timezone(timedelta(hours=8))
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")


def _default() -> dict:
    return {"schema": _SCHEMA, "items": [], "updated_at": None}


def _item(code: str, source: str, updated_at: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "source": source,
        "updated_at": updated_at or _now(),
    }


def _migrate_legacy_codes(data: dict) -> dict:
    """旧版仅 codes 数组的落盘格式 → 带 items 的 v1。"""
    codes = data.get("codes")
    if not isinstance(codes, list):
        return _default()
    stamp = data.get("updated_at")
    items = [_item(str(c), SOURCE_MANUAL, stamp) for c in codes if _CODE_RE.match(str(c or "").strip())]
    return {"schema": _SCHEMA, "items": items[:_MAX_CODES], "updated_at": stamp}


def _parse_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        if not _CODE_RE.match(code) or code in seen:
            continue
        seen.add(code)
        out.append({
            "code": code,
            "source": str(raw.get("source") or SOURCE_MANUAL),
            "updated_at": raw.get("updated_at"),
        })
        if len(out) >= _MAX_CODES:
            break
    return out


def _normalize_data(data: dict) -> dict:
    if not isinstance(data, dict):
        return _default()
    items = _parse_items(data.get("items"))
    if items:
        return {"schema": _SCHEMA, "items": items, "updated_at": data.get("updated_at")}
    if isinstance(data.get("codes"), list):
        return _migrate_legacy_codes(data)
    return _default()


def _load() -> dict:
    try:
        with open(WL_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return _normalize_data(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default()


def _save(data: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = WL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, WL_FILE)


def _export(data: dict) -> dict:
    items = list(data.get("items") or [])
    return {
        "schema": _SCHEMA,
        "codes": [it["code"] for it in items],
        "items": items,
        "updated_at": data.get("updated_at"),
    }


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


def replace_codes(codes: Any, *, default_source: str = SOURCE_MANUAL) -> dict:
    """全量覆盖自选股列表。"""
    clean = normalize_codes(codes)
    stamp = _now()
    with _LOCK:
        data = _default()
        data["items"] = [_item(c, default_source, stamp) for c in clean]
        data["updated_at"] = stamp
        _save(data)
    return get_watchlist()


def merge_plugin_codes(codes: Any, source: str) -> dict:
    """按来源合并插件自选股：linker 列表内标的标记为插件来源，仅插件来源的缺失项会被移除。"""
    clean = normalize_codes(codes)
    plugin_set = set(clean)
    stamp = _now()
    with _LOCK:
        data = _load()
        by_code = {it["code"]: dict(it) for it in data.get("items") or []}
        for code in list(by_code):
            if by_code[code].get("source") == source and code not in plugin_set:
                del by_code[code]
        for code in clean:
            by_code[code] = _item(code, source, stamp)
        manual_codes = [c for c, it in by_code.items() if it.get("source") != source]
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for code in clean:
            if code in by_code and code not in seen:
                ordered.append(by_code[code])
                seen.add(code)
        for code in manual_codes:
            if code in by_code and code not in seen:
                ordered.append(by_code[code])
                seen.add(code)
        data["items"] = ordered[:_MAX_CODES]
        data["updated_at"] = stamp
        _save(data)
    return get_watchlist()


def sync_codes_from_ui(codes: Any) -> dict:
    """前端全量同步：新增标为手动添加；保留项维持来源与时间；仅删除时不写 updated_at。"""
    clean = normalize_codes(codes)
    with _LOCK:
        data = _load()
        old_items = {it["code"]: dict(it) for it in data.get("items") or []}
        old_codes = set(old_items)
        new_codes = set(clean)
        added = new_codes - old_codes
        items: list[dict[str, Any]] = []
        for code in clean:
            if code in old_items:
                items.append(old_items[code])
            else:
                items.append(_item(code, SOURCE_MANUAL))
        data["items"] = items
        if added:
            data["updated_at"] = _now()
        _save(data)
    return get_watchlist()


def get_codes() -> list[str]:
    with _LOCK:
        data = _load()
    return [it["code"] for it in data.get("items") or []]


def get_codes_by_source(source: str) -> list[str]:
    with _LOCK:
        data = _load()
    return [it["code"] for it in data.get("items") or [] if it.get("source") == source]


def get_watchlist() -> dict:
    with _LOCK:
        data = _load()
    return _export(data)
