"""插件 HTTP 路由进程内注册表 —— 不落库，停用插件即清除。

公开 URL 固定在 ``/plugin/{plugin_id}/...``，避免覆盖系统 ``/api`` 与 SPA 路径。
"""

from __future__ import annotations

import inspect
import re
import threading
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .util import china_now

_LOCK = threading.Lock()
_ROUTES: dict[tuple[str, str], "PluginRoute"] = {}

_SEG_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
_MAX_PATH_LEN = 180
_DEFAULT_METHODS = ("GET", "HEAD")


@dataclass(frozen=True)
class PluginRoute:
    plugin_id: str
    path: str
    url: str
    description: str
    methods: tuple[str, ...]
    handler: Callable[..., Any]
    registered_at: str


def public_url(plugin_id: str, path: str = "") -> str:
    """公开 URL：``/plugin/{id}`` 或 ``/plugin/{id}/{path}``。"""
    pid = str(plugin_id or "").strip()
    rel = normalize_path(path)
    if not pid:
        raise ValueError("plugin_id 不能为空")
    if not rel:
        return f"/plugin/{pid}"
    return f"/plugin/{pid}/{rel}"


def normalize_path(raw: str | None) -> str:
    """相对路径：去掉首尾 ``/``，拒绝 ``..`` 与非法段。空串表示插件首页。"""
    text = str(raw or "").strip().replace("\\", "/")
    if not text or text == "/":
        return ""
    if text.startswith("/"):
        text = text.lstrip("/")
    if len(text) > _MAX_PATH_LEN:
        raise ValueError(f"路由 path 过长（>{_MAX_PATH_LEN}）")
    parts: list[str] = []
    for seg in text.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError("路由 path 不可包含 '..'")
        if not _SEG_RE.match(seg):
            raise ValueError(f"路由 path 含非法段：{seg!r}")
        parts.append(seg)
    return "/".join(parts)


def _norm_methods(methods: Sequence[str] | None) -> tuple[str, ...]:
    raw = list(methods) if methods else list(_DEFAULT_METHODS)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        m = str(item or "").strip().upper()
        if not m or m in seen:
            continue
        if not re.match(r"^[A-Z]+$", m):
            raise ValueError(f"非法 HTTP 方法：{item!r}")
        seen.add(m)
        out.append(m)
    if not out:
        raise ValueError("methods 不能为空")
    if "GET" in seen and "HEAD" not in seen:
        out.append("HEAD")
    return tuple(out)


def _html_handler(html: str) -> Callable[[], HTMLResponse]:
    body = str(html)

    def _serve() -> HTMLResponse:
        return HTMLResponse(body)

    return _serve


def register(
    plugin_id: str,
    path: str,
    description: str = "",
    *,
    handler: Callable[..., Any] | None = None,
    html: str | None = None,
    methods: Sequence[str] | None = None,
) -> PluginRoute:
    """登记一条插件路由；同插件同 path 可重复注册以更新说明与处理函数。"""
    pid = str(plugin_id or "").strip()
    if not pid:
        raise ValueError("plugin_id 不能为空")
    rel = normalize_path(path)
    desc = str(description or "").strip()
    if handler is not None and html is not None:
        raise ValueError("handler 与 html 只能提供一个")
    if handler is None and html is None:
        raise ValueError("须提供 handler 或 html")
    fn = handler if handler is not None else _html_handler(str(html))
    if not callable(fn):
        raise ValueError("handler 须可调用")
    meth = _norm_methods(methods)
    url = public_url(pid, rel)
    now = china_now().strftime("%Y-%m-%d %H:%M:%S")
    key = (pid, rel)
    with _LOCK:
        existing = _ROUTES[key] if key in _ROUTES else None
        rec = PluginRoute(
            plugin_id=pid,
            path=rel,
            url=url,
            description=desc,
            methods=meth,
            handler=fn,
            registered_at=existing.registered_at if existing else now,
        )
        _ROUTES[key] = rec
        return rec


def unregister_plugin(plugin_id: str) -> int:
    """清除某插件登记的全部路由，返回清除条数。"""
    pid = str(plugin_id or "").strip()
    if not pid:
        return 0
    with _LOCK:
        to_drop = [key for key in _ROUTES if key[0] == pid]
        for key in to_drop:
            del _ROUTES[key]
        return len(to_drop)


def get(plugin_id: str, path: str = "") -> PluginRoute | None:
    pid = str(plugin_id or "").strip()
    if not pid:
        return None
    try:
        rel = normalize_path(path)
    except ValueError:
        return None
    key = (pid, rel)
    with _LOCK:
        rec = _ROUTES[key] if key in _ROUTES else None
    return rec


def list_for_plugin(plugin_id: str) -> list[PluginRoute]:
    pid = str(plugin_id or "").strip()
    if not pid:
        return []
    with _LOCK:
        rows = [r for r in _ROUTES.values() if r.plugin_id == pid]
    return sorted(rows, key=lambda r: r.url)


def as_route_dicts(plugin_id: str) -> list[dict[str, Any]]:
    """供 ``GET /api/plugins`` 列表展示。"""
    return [
        {
            "url": r.url,
            "path": r.path,
            "description": r.description,
            "methods": list(r.methods),
        }
        for r in list_for_plugin(plugin_id)
    ]


def clear_all() -> None:
    """测试用：清空注册表。"""
    with _LOCK:
        _ROUTES.clear()


def _wants_request(fn: Callable[..., Any]) -> bool:
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    if not params:
        return False
    first = params[0]
    if first.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
        return False
    if first.name in {"request", "req"}:
        return True
    ann = first.annotation
    if ann is inspect.Signature.empty:
        return False
    return ann is Request or (isinstance(ann, str) and ann.endswith("Request"))


def _coerce_response(result: Any) -> Response:
    if isinstance(result, Response):
        return result
    if result is None:
        return Response(status_code=204)
    if isinstance(result, (bytes, bytearray)):
        return Response(content=bytes(result))
    if isinstance(result, (dict, list)):
        return JSONResponse(result)
    return HTMLResponse(str(result))


def dispatch(plugin_id: str, rest: str, request: Request) -> Response:
    """按已登记处理函数响应；锁外调用 handler，避免与 list/register 重入。"""
    rec = get(plugin_id, rest)
    if rec is None:
        return JSONResponse(
            {"error": "未找到插件路由", "detail": "未找到插件路由"},
            status_code=404,
        )
    method = (request.method or "GET").upper()
    if method not in rec.methods:
        return JSONResponse(
            {"error": "方法不允许", "detail": f"该路由不支持 {method}"},
            status_code=405,
        )
    try:
        if _wants_request(rec.handler):
            result = rec.handler(request)
        else:
            result = rec.handler()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        msg = str(exc).strip() or type(exc).__name__
        return JSONResponse(
            {"error": "插件路由执行失败", "detail": msg},
            status_code=500,
        )
    return _coerce_response(result)
