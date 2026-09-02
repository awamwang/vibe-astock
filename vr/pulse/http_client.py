"""预测市场 HTTP 客户端：可选 SOCKS/HTTP 代理（国内直连常失败）。"""
from __future__ import annotations

import os
from typing import Any

import httpx

# 优先专用环境变量；再读系统设置落盘；最后常见代理环境变量。
_PROXY_ENVS = (
    "VR_PULSE_PROXY",
)

_FALLBACK_ENVS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


def _config_proxy_url() -> str | None:
    try:
        from duanxian.proxy_config import get_configured_url  # noqa: PLC0415

        return get_configured_url()
    except Exception:  # noqa: BLE001
        return None


def pulse_proxy_url() -> str | None:
    """返回代理 URL；未配置则直连。例：socks5://127.0.0.1:7881"""
    for key in _PROXY_ENVS:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    cfg = _config_proxy_url()
    if cfg:
        return cfg
    for key in _FALLBACK_ENVS:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return None


def make_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """构造 AsyncClient；若配置了代理则走代理。"""
    proxy = pulse_proxy_url()
    if proxy and "proxy" not in kwargs:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)
