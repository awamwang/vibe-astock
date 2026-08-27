"""板块处理器 —— 将字符串经题材别名映射后与同花顺板块做匹配，维护待匹配列表。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from . import linker, service

_BEIJING = timezone(timedelta(hours=8))

_KIND_PRIORITY = ("conception", "industry", "region", "custom", "daily")

_SOURCE_SORT: dict[str, int] = {
    "emotion_industry": 10,
    "sector_flow": 20,
    "mood_block": 30,
    "fund_rotation": 40,
    "review_theme_tree": 50,
    "review_theme_structure": 60,
    "firstboard_theme": 70,
    "firstboard_industry": 80,
    "message_target": 100,
}

_SOURCE_LABELS: dict[str, str] = {
    "emotion_industry": "短线情绪·概念",
    "sector_flow": "板块资金·行业",
    "mood_block": "板块人气",
    "fund_rotation": "资金轮动",
    "review_theme_tree": "复盘·题材事件树",
    "review_theme_structure": "复盘·题材结构",
    "firstboard_theme": "涨停分析·题材",
    "firstboard_industry": "涨停分析·行业",
    "message_target": "消息分析·关联标的",
}

_LOCK = threading.Lock()
_ENSURE_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, Any]] = {}
_NAME_INDEX: dict[str, list[dict[str, Any]]] | None = None
_NAME_INDEX_AT: float | None = None
_ENSURE_SNAPSHOT_AT: Any = None
_ENSURE_TRIED: set[str] = set()


def _now() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _norm(raw: str) -> str:
    return str(raw or "").replace(" ", "").replace("\u3000", "").strip()


def _canonicalize(tag: str) -> str:
    try:
        from duanxian.theme_normalize import canonicalize_tag  # noqa: PLC0415

        return canonicalize_tag(tag)
    except Exception:  # noqa: BLE001
        return _norm(tag)


def _kind_rank(kind: str) -> int:
    try:
        return _KIND_PRIORITY.index(kind)
    except ValueError:
        return 99


def _block_ref(kind: str, kind_label: str, block_id: str, name: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "kind_label": kind_label,
        "id": block_id,
        "name": name,
    }


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for ref in sorted(refs, key=lambda r: (_kind_rank(str(r.get("kind") or "")), str(r.get("name") or ""))):
        key = (str(ref.get("kind") or ""), str(ref.get("id") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _pick_best(refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    deduped = _dedupe_refs(refs)
    return deduped[0] if deduped else None


def _unique_names_from_refs(refs: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ref in _dedupe_refs(refs):
        name = str(ref.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _suggested_canonical(status: str, candidates: list[dict[str, Any]]) -> str:
    if status != "partial":
        return ""
    return " ".join(_unique_names_from_refs(candidates))


def _build_name_index(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for kind, entry in (snapshot.get("kinds") or {}).items():
        if not isinstance(entry, dict):
            continue
        kind_label = str(entry.get("kind_label") or kind)
        seen_ids: set[tuple[str, str]] = set()

        def _add(bid: str, name: str) -> None:
            name = _norm(name)
            if not name:
                return
            key = (str(kind), str(bid))
            if key in seen_ids:
                return
            seen_ids.add(key)
            ref = _block_ref(str(kind), kind_label, str(bid), name)
            index.setdefault(name, []).append(ref)

        for row in entry.get("rows") or []:
            if isinstance(row, dict):
                _add(str(row.get("id") or ""), str(row.get("name") or ""))
        for bid, name in (entry.get("blocks") or {}).items():
            _add(str(bid), str(name or ""))
    return index


def _kind_has_data(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    blocks = entry.get("blocks")
    if isinstance(blocks, dict) and blocks:
        return True
    rows = entry.get("rows")
    return isinstance(rows, list) and bool(rows)


def _sync_ensure_state(snap: dict[str, Any]) -> None:
    global _ENSURE_SNAPSHOT_AT, _ENSURE_TRIED
    at = snap.get("updated_at")
    if at != _ENSURE_SNAPSHOT_AT:
        _ENSURE_SNAPSHOT_AT = at
        _ENSURE_TRIED = set()


def ensure_kinds_cached() -> list[str]:
    """确保各板块类型均有缓存；缺失的类型各触发一次 refresh_kind。"""
    refreshed: list[str] = []
    with _ENSURE_LOCK:
        snap = service.get_snapshot()
        _sync_ensure_state(snap)
        kinds_data = snap.get("kinds") or {}
        for kind in linker.list_kinds():
            if kind in _ENSURE_TRIED:
                continue
            if _kind_has_data(kinds_data.get(kind)):
                continue
            _ENSURE_TRIED.add(kind)
            try:
                service.refresh_kind(kind=kind)
                refreshed.append(kind)
                snap = service.get_snapshot()
                kinds_data = snap.get("kinds") or {}
            except Exception:  # noqa: BLE001
                pass
    if refreshed:
        invalidate_index()
    return refreshed


def _get_name_index() -> dict[str, list[dict[str, Any]]]:
    global _NAME_INDEX, _NAME_INDEX_AT
    ensure_kinds_cached()
    snap = service.get_snapshot()
    updated_at = snap.get("updated_at")
    with _LOCK:
        if _NAME_INDEX is not None and _NAME_INDEX_AT == updated_at:
            return _NAME_INDEX
        _NAME_INDEX = _build_name_index(snap)
        _NAME_INDEX_AT = updated_at
        return _NAME_INDEX


def invalidate_index() -> None:
    """板块缓存刷新后调用，使名称索引失效。"""
    global _NAME_INDEX, _NAME_INDEX_AT, _ENSURE_SNAPSHOT_AT, _ENSURE_TRIED
    with _LOCK:
        _NAME_INDEX = None
        _NAME_INDEX_AT = None
    with _ENSURE_LOCK:
        _ENSURE_SNAPSHOT_AT = None
        _ENSURE_TRIED = set()


def _partial_matches(mapped: str, index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if len(mapped) < 2:
        return []
    hits: list[dict[str, Any]] = []
    for name, refs in index.items():
        if mapped == name:
            continue
        if mapped in name or name in mapped:
            hits.extend(refs)
    return _dedupe_refs(hits)


def resolve_one(raw: str, *, index: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """解析单个字符串，返回匹配结果。"""
    raw_norm = _norm(raw)
    if not raw_norm:
        return {
            "raw": raw_norm,
            "mapped": "",
            "status": "empty",
            "block": None,
            "candidates": [],
        }
    mapped = _canonicalize(raw_norm)
    idx = index if index is not None else _get_name_index()

    exact_refs = idx.get(mapped) or []
    if exact_refs:
        best = _pick_best(exact_refs)
        return {
            "raw": raw_norm,
            "mapped": mapped,
            "status": "matched",
            "block": best,
            "candidates": _dedupe_refs(exact_refs),
        }

    partial = _partial_matches(mapped, idx)
    if partial:
        return {
            "raw": raw_norm,
            "mapped": mapped,
            "status": "partial",
            "block": None,
            "candidates": partial,
        }

    return {
        "raw": raw_norm,
        "mapped": mapped,
        "status": "unmatched",
        "block": None,
        "candidates": [],
    }


def _source_rank(source: str) -> int:
    return _SOURCE_SORT.get(source, 50)


def _merge_pending(key: str, item: dict[str, Any], source: str) -> None:
    prev = _PENDING.get(key)
    if not prev:
        _PENDING[key] = item
        return
    sources = set(prev.get("sources") or [])
    sources.add(source)
    prev["sources"] = sorted(sources, key=_source_rank)
    prev["source_labels"] = [_SOURCE_LABELS.get(s, s) for s in prev["sources"]]
    prev["sort_rank"] = min(_source_rank(s) for s in prev["sources"])
    prev["hit_count"] = int(prev.get("hit_count") or 0) + 1
    prev["updated_at"] = _now()
    if item.get("status") == "partial" and prev.get("status") != "partial":
        prev["status"] = "partial"
        prev["candidates"] = item.get("candidates") or []
    elif item.get("status") == "partial":
        merged = _dedupe_refs(list(prev.get("candidates") or []) + list(item.get("candidates") or []))
        prev["candidates"] = merged
    if prev.get("status") == "partial":
        prev["suggested_canonical"] = _suggested_canonical("partial", prev.get("candidates") or [])


def feed(source: str, strings: list[str]) -> list[dict[str, Any]]:
    """批量喂入字符串并更新待匹配列表，返回每条解析结果。"""
    cleaned = [_norm(s) for s in (strings or []) if _norm(s)]
    if not cleaned:
        return []
    index = _get_name_index()
    results: list[dict[str, Any]] = []
    with _LOCK:
        for raw in cleaned:
            result = resolve_one(raw, index=index)
            results.append(result)
            if result["status"] not in ("partial", "unmatched"):
                continue
            key = str(result["mapped"] or result["raw"])
            candidates = result.get("candidates") or []
            item = {
                "raw": result["raw"],
                "mapped": result["mapped"],
                "status": result["status"],
                "candidates": candidates,
                "suggested_canonical": _suggested_canonical(result["status"], candidates),
                "sources": [source],
                "source_labels": [_SOURCE_LABELS.get(source, source)],
                "sort_rank": _source_rank(source),
                "hit_count": 1,
                "updated_at": _now(),
            }
            _merge_pending(key, item, source)
    return results


def feed_review(market_facts: dict[str, Any] | None) -> None:
    """从复盘 market_facts 提取题材/行业字符串。"""
    if not isinstance(market_facts, dict):
        return
    tree = market_facts.get("theme_tree") or {}
    if isinstance(tree, dict) and tree.get("available"):
        tags = [str(t.get("tag") or "") for t in (tree.get("themes") or []) if isinstance(t, dict)]
        feed("review_theme_tree", tags)
    structure = market_facts.get("theme_structure") or {}
    if isinstance(structure, dict) and structure.get("available"):
        sectors = [
            str(t.get("sector") or "")
            for t in (structure.get("themes") or [])
            if isinstance(t, dict) and str(t.get("sector") or "") != "未分类"
        ]
        feed("review_theme_structure", sectors)


def feed_firstboard(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    themes = [str(o.get("tag") or "") for o in (payload.get("theme_options") or []) if isinstance(o, dict)]
    feed("firstboard_theme", themes)
    industries = [
        str(s.get("industry") or "")
        for s in (payload.get("stocks") or [])
        if isinstance(s, dict) and s.get("industry")
    ]
    feed("firstboard_industry", industries)


def feed_emotion(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    industries = [
        str(s.get("industry") or "")
        for s in (payload.get("lianban_stocks") or [])
        if isinstance(s, dict) and s.get("industry")
    ]
    feed("emotion_industry", industries)


def feed_overview(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    names = [str(s.get("name") or "") for s in (payload.get("sectors") or []) if isinstance(s, dict)]
    feed("sector_flow", names)
    pos = [n for n in names if n][:6]
    neg = list(reversed([n for n in names if n]))[:6]
    feed("fund_rotation", pos + neg)


def feed_mood_blocks(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    blocks = payload.get("blocks") or payload.get("items") or []
    names = [str(b.get("name") or "") for b in blocks if isinstance(b, dict)]
    feed("mood_block", names)


def feed_message_targets(items: list[Any]) -> None:
    names: list[str] = []
    for row in items or []:
        targets = row.get("targets") if isinstance(row, dict) else getattr(row, "targets", None)
        if not targets:
            continue
        for t in targets:
            kind = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", "")
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
            if kind in ("sector", "theme") and name:
                names.append(str(name))
    feed("message_target", names)


def get_pending() -> list[dict[str, Any]]:
    """返回排序后的待匹配列表。"""
    with _LOCK:
        rows = list(_PENDING.values())
    rows.sort(
        key=lambda r: (
            0 if r.get("status") == "partial" else 1,
            int(r.get("sort_rank") or 99),
            str(r.get("mapped") or r.get("raw") or ""),
        )
    )
    return rows


def export_pending() -> dict[str, Any]:
    rows = get_pending()
    return {
        "count": len(rows),
        "items": rows,
        "source_labels": dict(_SOURCE_LABELS),
        "updated_at": _now(),
    }


def remove_pending(*, mapped: str = "", raw: str = "") -> bool:
    key = _norm(mapped) or _norm(raw)
    if not key:
        return False
    with _LOCK:
        if key in _PENDING:
            del _PENDING[key]
            return True
        for k, item in list(_PENDING.items()):
            if _norm(item.get("raw") or "") == key or _norm(item.get("mapped") or "") == key:
                del _PENDING[k]
                return True
    return False


def clear_pending() -> None:
    with _LOCK:
        _PENDING.clear()
