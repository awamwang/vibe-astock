"""系统代理配置 —— 供 GlobalPercent 等需出境的拉取使用。

配置落盘：`{profile}/.duanxian-agents/config/proxy.json`
环境变量 `VR_PULSE_PROXY` 优先于本文件。
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Optional
from urllib.parse import urlparse

from . import paths as _paths
from .util import atomic_write_json

_CONFIG_DIR = ""
_CONFIG_PATH = ""
_SCHEMA = 1
_LOCK = threading.Lock()
_CACHE: Optional[dict[str, Any]] = None

_ALLOWED_SCHEMES = frozenset({
    "http", "https", "socks5", "socks5h", "socks4", "socks4a",
})


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH, _CACHE
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "proxy.json")
    _CACHE = None


class ProxyConfigError(ValueError):
    """代理配置非法。"""


def _default() -> dict[str, Any]:
    return {"schema": _SCHEMA, "enabled": False, "url": ""}


def _load_raw() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data = _default()
    try:
        raw = json.loads(open(_CONFIG_PATH, encoding="utf-8").read())
        if isinstance(raw, dict):
            data["enabled"] = bool(raw.get("enabled"))
            data["url"] = str(raw.get("url") or "").strip()
            data["schema"] = int(raw.get("schema") or _SCHEMA)
    except (FileNotFoundError, ValueError, OSError, TypeError):
        pass
    _CACHE = data
    return data


def validate_proxy_url(url: str) -> str:
    """校验并规范化代理 URL；空串表示清除。"""
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ProxyConfigError(
            f"代理协议须为 {', '.join(sorted(_ALLOWED_SCHEMES))} 之一"
        )
    if not parsed.hostname:
        raise ProxyConfigError("代理须包含主机名，例如 socks5://127.0.0.1:7881")
    if parsed.port is None and scheme.startswith("socks"):
        raise ProxyConfigError("SOCKS 代理须指定端口")
    # 拒绝明显危险字符
    if re.search(r"[\s<>\"']", text):
        raise ProxyConfigError("代理 URL 含非法字符")
    return text


def export_config() -> dict[str, Any]:
    """供 API / 设置页读取。"""
    with _LOCK:
        data = dict(_load_raw())
    env = (os.environ.get("VR_PULSE_PROXY") or "").strip()
    data["env_override"] = env or None
    data["effective_url"] = env or (data["url"] if data.get("enabled") else None) or None
    data["effective_source"] = (
        "env" if env
        else ("config" if data.get("enabled") and data.get("url") else None)
    )
    return data


def get_configured_url() -> str | None:
    """返回落盘配置中启用的代理；不含环境变量（由 http_client 合并）。"""
    with _LOCK:
        data = _load_raw()
        if data.get("enabled") and data.get("url"):
            return str(data["url"])
    return None


def save_config(*, enabled: bool, url: str) -> dict[str, Any]:
    """保存代理配置并刷新缓存。"""
    cleaned = validate_proxy_url(url)
    if enabled and not cleaned:
        raise ProxyConfigError("启用代理时须填写代理地址")
    payload = {"schema": _SCHEMA, "enabled": bool(enabled), "url": cleaned}
    os.makedirs(_CONFIG_DIR or str(_paths.config_dir()), exist_ok=True)
    path = _CONFIG_PATH or os.path.join(str(_paths.config_dir()), "proxy.json")
    with _LOCK:
        if not atomic_write_json(path, payload):
            raise OSError(f"写入失败: {path}")
        global _CACHE
        _CACHE = dict(payload)
    return export_config()


def clear_config() -> dict[str, Any]:
    """关闭并清空落盘代理。"""
    return save_config(enabled=False, url="")
