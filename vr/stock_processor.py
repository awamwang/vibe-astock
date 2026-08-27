"""股票处理器 —— 将名称或代码与 A 股全量列表做匹配。"""

from __future__ import annotations

import re
from typing import Any

import stock_universe

_CODE_RE = re.compile(r"^\d{6}$")


def _norm_name(raw: str | None) -> str:
    return (raw or "").replace("\u3000", " ").replace(" ", "").strip()


def _norm_code(raw: str | None) -> str:
    c = (raw or "").strip()
    if not c:
        return ""
    c = c.zfill(6)
    return c if _CODE_RE.match(c) else ""


def make_key(*, code: str | None = None, name: str | None = None) -> str:
    """生成批量解析用的稳定键；有合法 code 时优先用 code。"""
    c = _norm_code(code)
    if c:
        return f"c:{c}"
    n = _norm_name(name)
    return f"n:{n}" if n else ""


def _stock_ref(item: stock_universe.StockItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "name": item.name,
        "market": item.market,
        "types": list(item.types),
    }


def resolve_one(*, code: str | None = None, name: str | None = None) -> dict[str, Any]:
    """解析单条查询：优先 code，否则名称精确匹配（含去括号）。"""
    key = make_key(code=code, name=name)
    c = _norm_code(code)
    n = _norm_name(name)
    if not key:
        return {
            "key": "",
            "code": c or None,
            "name": n or None,
            "status": "empty",
            "stock": None,
        }

    stock_universe.ensure_loaded()
    hit: stock_universe.StockItem | None = None
    if c:
        hit = stock_universe.get_stock_by_code(c)
    elif n:
        resolved = stock_universe.resolve_code_by_name(n)
        if resolved:
            hit = stock_universe.get_stock_by_code(resolved)

    if hit:
        return {
            "key": key,
            "code": hit.code,
            "name": hit.name,
            "status": "matched",
            "stock": _stock_ref(hit),
        }
    return {
        "key": key,
        "code": c or None,
        "name": n or None,
        "status": "unmatched",
        "stock": None,
    }


def resolve_many(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量解析，保持输入顺序并去重。"""
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in queries or []:
        code = row.get("code") if isinstance(row, dict) else None
        name = row.get("name") if isinstance(row, dict) else None
        key = make_key(code=str(code) if code else None, name=str(name) if name else None)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append({"code": code, "name": name})
    if not cleaned:
        return []
    return [
        resolve_one(
            code=str(q.get("code") or "") or None,
            name=str(q.get("name") or "") or None,
        )
        for q in cleaned
    ]


def index_info() -> dict[str, Any]:
    """返回股票列表是否就绪及规模。"""
    meta = stock_universe.get_load_meta()
    status = stock_universe.export_status()
    return {
        "ready": stock_universe.is_loaded(),
        "refreshing": status.get("refreshing", False),
        "count": status.get("count", 0),
        "updated_at": status.get("updated_at"),
        "source": status.get("source"),
        "error": status.get("error"),
    }


def export_resolve(queries: list[dict[str, Any]]) -> dict[str, Any]:
    """批量解析并附带按键索引的映射表。"""
    items = resolve_many(queries)
    return {
        "items": items,
        "by_key": {str(item.get("key") or ""): item for item in items if item.get("key")},
        "index": index_info(),
    }
