"""AKTools HTTP 客户端 —— 优先打本机 AKTools，失败再回退本地 akshare。

默认基址 `http://127.0.0.1:8988`，可用环境变量 `AKTOOLS_BASE` 覆盖。
接口形态：`GET {base}/api/public/{item_id}?…`
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests

_DEFAULT_BASE = "http://127.0.0.1:8988"
_TIMEOUT = float(os.environ.get("AKTOOLS_TIMEOUT", "25"))


def base_url() -> str:
    return (os.environ.get("AKTOOLS_BASE") or _DEFAULT_BASE).rstrip("/")


def available(timeout: float = 2.0) -> bool:
    try:
        r = requests.get(f"{base_url()}/version", timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def version() -> Optional[dict[str, Any]]:
    try:
        r = requests.get(f"{base_url()}/version", timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def public(item_id: str, **params: Any) -> Any:
    """调用 `/api/public/{item_id}`。成功返回 JSON（多为 list[dict]）。失败抛错。"""
    q = {k: v for k, v in params.items() if v is not None and v != ""}
    r = requests.get(
        f"{base_url()}/api/public/{item_id}",
        params=q or None,
        timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"AKTools {item_id} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def status() -> dict[str, Any]:
    """供设置页 / 健康检查。"""
    ver = version()
    ok = ver is not None
    return {
        "available": ok,
        "base": base_url(),
        "version": ver,
        "hint": None
        if ok
        else "未检测到 AKTools：确认已 pip install aktools，并重启本项目后端（会自动拉起 :8988）",
    }
