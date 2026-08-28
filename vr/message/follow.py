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


def initial_impact_with_follow(
    level: str,
    *,
    title: str = "",
    summary: str = "",
    detail: str = "",
    keywords: list[str] | None = None,
    follow_keywords: list[str] | None = None,
) -> str:
    """导入/转换新建时：命中关注词则影响等级 +1；后续读写不再改等级。"""
    kws = follow_keywords if follow_keywords is not None else load_keywords()
    matched = match_in_text(kws, title, summary, detail, keywords or [])
    if matched:
        return boost_impact_level(level)
    return str(level or "medium")


def enrich_follow(msg: AnalyzedMessage, keywords: list[str] | None = None) -> AnalyzedMessage:
    """为分析消息填充关注命中字段（不改写已入库的影响等级）。"""
    kws = keywords if keywords is not None else load_keywords()
    matched = match_in_text(kws, msg.title, msg.summary, msg.detail, msg.keywords)
    msg.followed = bool(matched)
    msg.matched_follow_keywords = matched
    return msg
