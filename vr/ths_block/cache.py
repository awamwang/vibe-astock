"""同花顺板块全局内存缓存（不落盘）。"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None


def get() -> dict[str, Any] | None:
    with _LOCK:
        return _CACHE.copy() if _CACHE else None


def set_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        global _CACHE
        _CACHE = data
        return _CACHE.copy()
