"""消息生效/结束时间计算。"""

from __future__ import annotations

from datetime import datetime, timedelta

from .schemas import AnalyzedMessage

DEFAULT_END_DAYS = 5
_STORAGE_FMT = "%Y-%m-%d %H:%M:%S"


def effective_at_dt(msg: AnalyzedMessage) -> str:
    """回测口径：定时生效取 effective_at，立即生效取 produced_at。"""
    if msg.effective_mode == "scheduled" and msg.effective_at and str(msg.effective_at).strip():
        return str(msg.effective_at).strip()
    return msg.produced_at


def _parse_storage_dt(value: str) -> datetime | None:
    text = (value or "").strip().replace("T", " ")
    for fmt in (_STORAGE_FMT, "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def add_days_to_storage_dt(value: str, days: int) -> str:
    parsed = _parse_storage_dt(value)
    if parsed is None:
        return value
    return (parsed + timedelta(days=days)).strftime(_STORAGE_FMT)


def effective_end_at(msg: AnalyzedMessage, *, default_days: int = DEFAULT_END_DAYS) -> str:
    """结束时间：有 end_at 取 end_at，否则生效时间 + default_days。"""
    if msg.end_at and str(msg.end_at).strip():
        return str(msg.end_at).strip()
    return add_days_to_storage_dt(effective_at_dt(msg), default_days)


def has_explicit_end_at(msg: AnalyzedMessage) -> bool:
    return bool(msg.end_at and str(msg.end_at).strip())
