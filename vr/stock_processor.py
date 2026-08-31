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


_CODE_IN_TEXT_RE = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SZ|SH|BJ|sz|sh|bj))?(?!\d)")
_NAME_CODE_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9·．.]{2,30}?)\s*[（(]\s*(\d{6})(?:\.(?:SZ|SH|BJ|sz|sh|bj))?\s*[）)]"
)


def _find_known_names(text: str, names: list[str], *, min_len: int = 3) -> list[str]:
    """在正文中按最长优先、互不重叠扫描已知名称。"""
    if not text or not names:
        return []
    ordered = sorted({n for n in names if n and len(n) >= min_len}, key=len, reverse=True)
    occupied = [False] * len(text)
    hits: list[str] = []
    seen: set[str] = set()
    for name in ordered:
        start = 0
        while True:
            i = text.find(name, start)
            if i < 0:
                break
            end = i + len(name)
            if not any(occupied[i:end]):
                for j in range(i, end):
                    occupied[j] = True
                if name not in seen:
                    seen.add(name)
                    hits.append(name)
                break
            start = i + 1
    return hits


def scan_text(text: str, *, min_name_len: int = 3) -> list[dict[str, Any]]:
    """从正文扫描个股代码/名称，经 resolve 返回解析结果（去重）。"""
    raw = text or ""
    if not raw.strip():
        return []

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(*, code: str | None = None, name: str | None = None) -> None:
        key = make_key(code=code, name=name)
        if not key or key in seen:
            return
        seen.add(key)
        queries.append({"code": code, "name": name})

    for m in _NAME_CODE_RE.finditer(raw):
        _add(code=m.group(2), name=m.group(1).strip())

    for m in _CODE_IN_TEXT_RE.finditer(raw):
        _add(code=m.group(1))

    try:
        stock_universe.ensure_loaded()
        name_map = stock_universe.get_name_to_code()
    except Exception:  # noqa: BLE001
        name_map = {}
    for name in _find_known_names(raw, list(name_map.keys()), min_len=min_name_len):
        # 已按代码收录过的标的，不再用名称键重复加入
        code = name_map.get(name)
        if code and f"c:{code}" in seen:
            continue
        _add(name=name)

    rows = resolve_many(queries)
    out: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    seen_unmatched: set[str] = set()
    for row in rows:
        stock = row.get("stock") if isinstance(row.get("stock"), dict) else None
        if stock and stock.get("code"):
            code = str(stock["code"])
            if code in seen_codes:
                continue
            seen_codes.add(code)
            out.append(row)
            continue
        key = str(row.get("key") or "")
        if key in seen_unmatched:
            continue
        seen_unmatched.add(key)
        out.append(row)
    return out
