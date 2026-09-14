"""同花顺热点主题日限缓存 —— 参考开盘啦，每日自动最多请求一次。

落盘：``{agents}/cache/ths_theme/{date}.json``
``force=False``：当日已有落盘/内存则复用；``force=True``（手动刷新）才强制重拉。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from profile_paths import agents_dir

_LOCK = threading.Lock()
_mem_date: str | None = None
_mem_entry: dict[str, Any] | None = None
_CACHE_DIR = ""


def _rebind_cache_dir() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(agents_dir() / "cache" / "ths_theme")


_rebind_cache_dir()


def _china_today() -> str:
    try:
        from duanxian.util import china_today  # noqa: PLC0415

        return china_today()
    except Exception:  # noqa: BLE001
        from datetime import datetime, timezone, timedelta

        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _now() -> str:
    try:
        from duanxian.util import china_now  # noqa: PLC0415

        return china_now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        from datetime import datetime, timezone, timedelta

        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _archive_path(date: str) -> str:
    if not _CACHE_DIR:
        _rebind_cache_dir()
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _kind_has_data(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    blocks = entry.get("blocks")
    if isinstance(blocks, dict) and blocks:
        return True
    rows = entry.get("rows")
    return isinstance(rows, list) and bool(rows)


def _load_archive(date: str) -> dict[str, Any] | None:
    path = _archive_path(date)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        entry = data.get("entry")
        if not _kind_has_data(entry):
            return None
        out = dict(data)
        out["from_cache"] = True
        out["fetched_date"] = str(out.get("fetched_date") or date)
        out["entry"] = dict(entry)
        return out
    except Exception:  # noqa: BLE001
        return None


def _save_archive(
    *,
    entry: dict[str, Any],
    ths_dir: str | None,
    warnings: list[str] | None = None,
) -> None:
    date = _china_today()
    try:
        if not _CACHE_DIR:
            _rebind_cache_dir()
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        body = {
            "updated_at": _now(),
            "fetched_date": date,
            "ths_dir": ths_dir,
            "from_cache": False,
            "warnings": list(warnings or []),
            "entry": entry,
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def entry_is_today(entry: Any) -> bool:
    """内存中的主题条目是否已是今日拉取。"""
    if not _kind_has_data(entry):
        return False
    if not isinstance(entry, dict):
        return False
    return str(entry.get("fetched_date") or "") == _china_today()


def load_today() -> dict[str, Any] | None:
    """读今日主题缓存（内存优先，否则落盘）。"""
    global _mem_date, _mem_entry
    today = _china_today()
    with _LOCK:
        if _mem_entry is not None and _mem_date == today and _kind_has_data(_mem_entry):
            return {
                "updated_at": None,
                "fetched_date": today,
                "from_cache": True,
                "entry": dict(_mem_entry),
            }
    archived = _load_archive(today)
    if not archived:
        return None
    entry = archived.get("entry")
    if not isinstance(entry, dict):
        return None
    with _LOCK:
        _mem_date = today
        _mem_entry = dict(entry)
    return archived


def save_today(
    entry: dict[str, Any],
    *,
    ths_dir: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """写入今日主题缓存（内存 + 落盘），并给 entry 打上 fetched_date。"""
    global _mem_date, _mem_entry
    today = _china_today()
    stored = dict(entry)
    stored["fetched_date"] = today
    stored["from_cache"] = False
    with _LOCK:
        _mem_date = today
        _mem_entry = dict(stored)
    _save_archive(entry=stored, ths_dir=ths_dir, warnings=warnings)
    return stored


def clear_mem() -> None:
    """测试用：清空内存日限缓存。"""
    global _mem_date, _mem_entry
    with _LOCK:
        _mem_date = None
        _mem_entry = None
