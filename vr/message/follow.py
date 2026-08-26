"""消息关注词命中判定。"""

from __future__ import annotations

from duanxian.message_follow_keywords import load_keywords, match_in_text

from .schemas import AnalyzedMessage

_IMPACT_ORDER = ("noise", "low", "medium", "high", "critical")


def boost_impact_level(level: str) -> str:
    """影响等级升一档（封顶 critical）。"""
    lv = str(level or "medium")
    try:
        idx = _IMPACT_ORDER.index(lv)
    except ValueError:
        return lv
    if idx < len(_IMPACT_ORDER) - 1:
        return _IMPACT_ORDER[idx + 1]
    return lv


def enrich_follow(msg: AnalyzedMessage, keywords: list[str] | None = None) -> AnalyzedMessage:
    """为分析消息填充关注命中字段；命中时影响等级 +1。"""
    kws = keywords if keywords is not None else load_keywords()
    matched = match_in_text(kws, msg.title, msg.summary, msg.detail, msg.keywords)
    msg.followed = bool(matched)
    msg.matched_follow_keywords = matched
    if matched:
        msg.impact_level = boost_impact_level(msg.impact_level)
    return msg
