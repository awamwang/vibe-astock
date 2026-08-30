"""消息关注词 / 关注板块命中判定。"""

from __future__ import annotations

from typing import Any

from duanxian.message_follow_blocks import load_blocks, match_in_targets
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


def follow_should_boost(
    *,
    title: str = "",
    summary: str = "",
    detail: str = "",
    keywords: list[str] | None = None,
    targets: list[Any] | None = None,
    follow_keywords: list[str] | None = None,
    follow_blocks: list[dict[str, str]] | None = None,
) -> tuple[bool, list[str], list[dict[str, str]]]:
    """关注词或关注板块命中任一则升档；二者共用同一套升档条件，不叠加。"""
    kws = follow_keywords if follow_keywords is not None else load_keywords()
    blocks = follow_blocks if follow_blocks is not None else load_blocks()
    matched_kws = match_in_text(kws, title, summary, detail, keywords or [])
    matched_blocks = match_in_targets(blocks, targets)
    return bool(matched_kws or matched_blocks), matched_kws, matched_blocks


def initial_impact_with_follow(
    level: str,
    *,
    title: str = "",
    summary: str = "",
    detail: str = "",
    keywords: list[str] | None = None,
    targets: list[Any] | None = None,
    follow_keywords: list[str] | None = None,
    follow_blocks: list[dict[str, str]] | None = None,
) -> str:
    """导入/转换新建时：命中关注词或关注板块则影响等级 +1；后续读写不再改等级。"""
    should, _, _ = follow_should_boost(
        title=title,
        summary=summary,
        detail=detail,
        keywords=keywords,
        targets=targets,
        follow_keywords=follow_keywords,
        follow_blocks=follow_blocks,
    )
    if should:
        return boost_impact_level(level)
    return str(level or "medium")


def enrich_follow(
    msg: AnalyzedMessage,
    keywords: list[str] | None = None,
    follow_blocks: list[dict[str, str]] | None = None,
) -> AnalyzedMessage:
    """为分析消息填充关注命中字段（不改写已入库的影响等级）。"""
    kws = keywords if keywords is not None else load_keywords()
    blocks = follow_blocks if follow_blocks is not None else load_blocks()
    matched_kws = match_in_text(kws, msg.title, msg.summary, msg.detail, msg.keywords)
    matched_blocks = match_in_targets(blocks, msg.targets)
    msg.followed = bool(matched_kws or matched_blocks)
    msg.matched_follow_keywords = matched_kws
    msg.matched_follow_blocks = [
        str(b.get("name") or b.get("id") or "").strip()
        for b in matched_blocks
        if str(b.get("name") or b.get("id") or "").strip()
    ]
    return msg
