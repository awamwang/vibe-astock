"""消息关注词命中判定。"""

from __future__ import annotations

from duanxian.message_follow_keywords import load_keywords, match_in_text

from .schemas import AnalyzedMessage


def enrich_follow(msg: AnalyzedMessage, keywords: list[str] | None = None) -> AnalyzedMessage:
    """为分析消息填充关注命中字段。"""
    kws = keywords if keywords is not None else load_keywords()
    matched = match_in_text(kws, msg.title, msg.summary, msg.detail, msg.keywords)
    msg.followed = bool(matched)
    msg.matched_follow_keywords = matched
    return msg
