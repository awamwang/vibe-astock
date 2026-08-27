"""当前股票与消息标的匹配。"""

from __future__ import annotations

from ..ths_block import match as block_match

from .schemas import AnalyzedMessage


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
