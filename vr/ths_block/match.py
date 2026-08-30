"""按成分股匹配板块目标。"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from . import processor, service, stocks as block_stocks

_BLOCK_TARGET_KINDS = frozenset({"sector", "theme"})


def _norm_code(code: str) -> str:
    c = (code or "").strip()
    if not c:
        return ""
    z = c.zfill(6)
    return z if len(z) == 6 and z.isdigit() else ""


@lru_cache(maxsize=512)
def _block_stock_codes(ths_dir: str, kind: str, block_id: str) -> frozenset[str]:
    try:
        items = block_stocks.list_block_stocks(Path(ths_dir), kind=kind, block_id=block_id)
    except (OSError, FileNotFoundError, ValueError):
        return frozenset()
    return frozenset(
        c for x in items if (c := _norm_code(str(x.get("code") or "")))
    )


def block_contains_stock(stock_code: str, *, kind: str, block_id: str) -> bool:
    code = _norm_code(stock_code)
    if not code:
        return False
    snap = service.get_snapshot()
    ths_dir = snap.get("ths_dir") if snap else None
    if not ths_dir:
        return False
    return code in _block_stock_codes(str(ths_dir), kind.strip(), block_id.strip())


def _resolve_block_ref(name: str) -> tuple[str, str] | None:
    raw = (name or "").strip()
    if not raw:
        return None
    resolved = processor.resolve_one(raw)
    if resolved.get("status") != "matched":
        return None
    block = resolved.get("block")
    if not block:
        return None
    kind = str(block.get("kind") or "").strip()
    block_id = str(block.get("id") or "").strip()
    if not kind or not block_id:
        return None
    return kind, block_id


def block_name_stock_count(name: str) -> int:
    """板块名称对应成分股数量；无法解析时返回极大值（排序靠后）。"""
    ref = _resolve_block_ref(name)
    if not ref:
        return 10**9
    kind, block_id = ref
    snap = service.get_snapshot()
    ths_dir = snap.get("ths_dir") if snap else None
    if not ths_dir:
        return 10**9
    return len(_block_stock_codes(str(ths_dir), kind, block_id))


def target_name_contains_stock(name: str, stock_code: str) -> bool:
    ref = _resolve_block_ref(name)
    if not ref:
        return False
    kind, block_id = ref
    return block_contains_stock(stock_code, kind=kind, block_id=block_id)


def analyzed_ids_with_stock_in_block_targets(
    conn: sqlite3.Connection,
    stock_code: str,
) -> dict[str, int]:
    """返回板块/主题目标成分股含指定股票的分析消息 id → 命中板块中成分股数最少者。"""
    code = _norm_code(stock_code)
    if not code:
        return {}
    placeholders = ",".join("?" * len(_BLOCK_TARGET_KINDS))
    rows = conn.execute(
        f"""
        SELECT analyzed_id, name FROM impact_target
        WHERE kind IN ({placeholders})
          AND name IS NOT NULL AND TRIM(name) != ''
        """,
        tuple(_BLOCK_TARGET_KINDS),
    ).fetchall()
    out: dict[str, int] = {}
    # name → (是否命中, 成分股数)；未命中时 count 无意义
    checked: dict[str, tuple[bool, int]] = {}
    for row in rows:
        name = str(row["name"] or "").strip()
        if not name:
            continue
        cached = checked.get(name)
        if cached is None:
            hit = target_name_contains_stock(name, code)
            count = block_name_stock_count(name) if hit else 10**9
            cached = (hit, count)
            checked[name] = cached
        hit, count = cached
        if not hit:
            continue
        aid = str(row["analyzed_id"])
        prev = out.get(aid)
        if prev is None or count < prev:
            out[aid] = count
    return out
