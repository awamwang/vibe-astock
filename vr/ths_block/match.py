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


def target_name_contains_stock(name: str, stock_code: str) -> bool:
    raw = (name or "").strip()
    if not raw:
        return False
    resolved = processor.resolve_one(raw)
    if resolved.get("status") != "matched":
        return False
    block = resolved.get("block")
    if not block:
        return False
    kind = str(block.get("kind") or "")
    block_id = str(block.get("id") or "")
    if not kind or not block_id:
        return False
    return block_contains_stock(stock_code, kind=kind, block_id=block_id)


def analyzed_ids_with_stock_in_block_targets(
    conn: sqlite3.Connection,
    stock_code: str,
) -> set[str]:
    """返回板块/主题目标成分股包含指定股票的分析消息 id。"""
    code = _norm_code(stock_code)
    if not code:
        return set()
    placeholders = ",".join("?" * len(_BLOCK_TARGET_KINDS))
    rows = conn.execute(
        f"""
        SELECT analyzed_id, name FROM impact_target
        WHERE kind IN ({placeholders})
          AND name IS NOT NULL AND TRIM(name) != ''
        """,
        tuple(_BLOCK_TARGET_KINDS),
    ).fetchall()
    out: set[str] = set()
    checked: dict[str, bool] = {}
    for row in rows:
        name = str(row["name"] or "").strip()
        if not name:
            continue
        hit = checked.get(name)
        if hit is None:
            hit = target_name_contains_stock(name, code)
            checked[name] = hit
        if hit:
            out.add(str(row["analyzed_id"]))
    return out
