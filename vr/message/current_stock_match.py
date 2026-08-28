"""当前股票与消息标的匹配。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ths_block import match as block_match

from .schemas import AnalyzedMessage


@dataclass(frozen=True)
class CurrentStockMatchIds:
    """跟随当前股票时的命中分层：标的 / 内容摘要 / 板块成分。"""

    target: frozenset[str]
    content: frozenset[str]
    block: frozenset[str]

    def all_ids(self) -> set[str]:
        return set(self.target) | set(self.content) | set(self.block)


def resolve_stock_name(stock_code: str) -> str:
    """按代码解析股票名称；解析失败返回空串。"""
    code = (stock_code or "").strip().zfill(6)
    if not code.isdigit() or len(code) != 6:
        return ""
    try:
        import stock_universe

        stock_universe.ensure_loaded()
        item = stock_universe.get_stock_by_code(code)
    except (ImportError, OSError, RuntimeError, ValueError, TypeError):
        return ""
    return (item.name if item else "") or ""


def collect_match_ids(conn: sqlite3.Connection, stock_code: str) -> CurrentStockMatchIds:
    """收集直接标的、内容/摘要含名称、板块成分股三类命中消息 id。"""
    code = (stock_code or "").strip().zfill(6)
    if not code.isdigit() or len(code) != 6:
        return CurrentStockMatchIds(frozenset(), frozenset(), frozenset())

    target: set[str] = set()
    for row in conn.execute(
        "SELECT DISTINCT analyzed_id FROM impact_target WHERE code = ?",
        (code,),
    ):
        target.add(str(row["analyzed_id"]))

    block = set(block_match.analyzed_ids_with_stock_in_block_targets(conn, code))

    content: set[str] = set()
    name = resolve_stock_name(code).strip()
    if name:
        like = f"%{name}%"
        for row in conn.execute(
            """
            SELECT id FROM analyzed_message
            WHERE summary LIKE ? OR detail LIKE ?
            """,
            (like, like),
        ):
            content.add(str(row["id"]))

    return CurrentStockMatchIds(
        target=frozenset(target),
        content=frozenset(content),
        block=frozenset(block),
    )


def enrich_current_stock(msg: AnalyzedMessage, stock_code: str | None) -> AnalyzedMessage:
    """填充当前股票命中的板块目标名称列表。"""
    code = (stock_code or "").strip()
    if not code:
        msg.matched_current_stock_blocks = []
        return msg
    names: list[str] = []
    seen: set[str] = set()
    for t in msg.targets:
        if t.kind not in ("sector", "theme"):
            continue
        name = (t.name or "").strip()
        if not name or name in seen:
            continue
        if block_match.target_name_contains_stock(name, code):
            seen.add(name)
            names.append(name)
    msg.matched_current_stock_blocks = names
    return msg
