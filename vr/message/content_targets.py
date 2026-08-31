"""从消息正文扫描个股/板块，经处理器解析后与已有标的去重增量合并。"""

from __future__ import annotations

from typing import Any, Iterable

from .schemas import ImpactTarget


def _norm_name(raw: str | None) -> str:
    return (raw or "").replace("\u3000", "").replace(" ", "").strip()


def _as_dict(t: ImpactTarget | dict[str, Any]) -> dict[str, Any]:
    if isinstance(t, ImpactTarget):
        return t.model_dump()
    return {
        "kind": str(t.get("kind") or "other"),
        "code": (str(t["code"]).strip() if t.get("code") not in (None, "") else None),
        "name": str(t.get("name") or "").strip(),
    }


def merge_targets(
    existing: Iterable[ImpactTarget | dict[str, Any]] | None,
    *extra_groups: Iterable[ImpactTarget | dict[str, Any]],
) -> list[ImpactTarget]:
    """已有标的在前，后续组增量追加；同身份只保留首次。"""
    out: list[ImpactTarget] = []
    seen_stock_codes: set[str] = set()
    seen_stock_names: set[str] = set()
    seen_block_names: set[str] = set()
    seen_other: set[tuple[str, str, str]] = set()
    groups: list[Iterable[ImpactTarget | dict[str, Any]]] = []
    if existing:
        groups.append(existing)
    groups.extend(extra_groups)
    for group in groups:
        for raw in group or []:
            d = _as_dict(raw)
            code = str(d.get("code") or "").strip()
            name = _norm_name(str(d.get("name") or ""))
            if not name and code:
                name = code
                d["name"] = code
            if not name and not code:
                continue
            kind = d["kind"] if d["kind"] in ("market", "sector", "theme", "stock", "other") else "other"
            if kind == "stock":
                if code and code in seen_stock_codes:
                    continue
                if name and name in seen_stock_names:
                    continue
                if code:
                    seen_stock_codes.add(code)
                if name:
                    seen_stock_names.add(name)
            elif kind in ("sector", "theme"):
                if not name or name in seen_block_names:
                    continue
                seen_block_names.add(name)
            else:
                key = (kind, code, name)
                if key in seen_other:
                    continue
                seen_other.add(key)
            out.append(ImpactTarget(kind=kind, code=code or None, name=name))
    return out


def _stocks_from_scan(rows: list[dict[str, Any]]) -> list[ImpactTarget]:
    out: list[ImpactTarget] = []
    for row in rows or []:
        stock = row.get("stock") if isinstance(row.get("stock"), dict) else None
        if stock:
            code = str(stock.get("code") or "").strip() or None
            name = str(stock.get("name") or "").strip()
            if code or name:
                out.append(ImpactTarget(kind="stock", code=code, name=name or code or ""))
            continue
        code = str(row.get("code") or "").strip() or None
        name = str(row.get("name") or "").strip()
        if code or name:
            out.append(ImpactTarget(kind="stock", code=code, name=name or code or ""))
    return out


def _sectors_from_scan(rows: list[dict[str, Any]]) -> list[ImpactTarget]:
    out: list[ImpactTarget] = []
    for row in rows or []:
        block = row.get("block") if isinstance(row.get("block"), dict) else None
        if block:
            code = str(block.get("id") or "").strip() or None
            name = str(block.get("name") or "").strip()
            if name:
                out.append(ImpactTarget(kind="sector", code=code, name=name))
            continue
        name = str(row.get("mapped") or row.get("raw") or row.get("name") or "").strip()
        if name:
            out.append(ImpactTarget(kind="sector", code=None, name=name))
    return out


def resolve_content_targets(text: str) -> list[ImpactTarget]:
    """扫描正文中的个股与板块，经对应处理器解析。"""
    body = (text or "").strip()
    if not body:
        return []
    stock_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    try:
        import stock_processor  # noqa: PLC0415

        stock_rows = stock_processor.scan_text(body)
    except Exception:  # noqa: BLE001
        stock_rows = []
    try:
        from ths_block import processor as block_processor  # noqa: PLC0415

        sector_rows = block_processor.scan_text(body)
    except Exception:  # noqa: BLE001
        sector_rows = []
    return merge_targets(
        None,
        _stocks_from_scan(stock_rows),
        _sectors_from_scan(sector_rows),
    )


def enrich_targets_from_content(
    text: str,
    *,
    existing: Iterable[ImpactTarget | dict[str, Any]] | None = None,
) -> list[ImpactTarget]:
    """已有标的保留在前，正文解析结果去重后增量追加。"""
    return merge_targets(existing, resolve_content_targets(text))


def attach_targets_to_draft(draft: Any) -> Any:
    """就地充实草稿 targets / meta._targets_json（保留已有，正文增量）。"""
    body = f"{getattr(draft, 'title', '') or ''}\n{getattr(draft, 'content', '') or ''}"
    existing = list(getattr(draft, "targets", None) or [])
    merged = enrich_targets_from_content(body, existing=existing)
    draft.targets = merged
    meta = dict(getattr(draft, "meta", None) or {})
    meta["_targets_json"] = [t.model_dump() for t in merged]
    draft.meta = meta
    return draft
