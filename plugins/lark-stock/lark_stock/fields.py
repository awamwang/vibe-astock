"""多维表格单元格的日期匹配与展示。"""

from __future__ import annotations

import datetime
from typing import Any

try:
    from zoneinfo import ZoneInfo

    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    _CN_TZ = datetime.timezone(datetime.timedelta(hours=8))


def shanghai_midnight_ms(day: str) -> int:
    """上海时区当天 0 点的毫秒时间戳，供日期列精确筛选。"""
    year, month, date = (int(part) for part in str(day).split("-"))
    moment = datetime.datetime(year, month, date, tzinfo=_CN_TZ)
    return int(moment.timestamp() * 1000)


def day_tokens(day: str) -> list[str]:
    """同一天在表格里常见的写法，顺序稳定、不含重复。"""
    year, month, date = str(day).split("-")
    month_i, date_i = str(int(month)), str(int(date))
    raw = [
        day,
        f"{year}/{month}/{date}",
        f"{year}/{month_i}/{date_i}",
        f"{year}.{month}.{date}",
        f"{year}.{month_i}.{date_i}",
        f"{year}{month}{date}",
        f"{year}年{month_i}月{date_i}日",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for token in raw:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def flatten_cell(value: Any) -> str:
    """把单元格收成可比较的文本。富文本取 text。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, list):
        parts = [flatten_cell(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "link"):
            if value.get(key) not in (None, ""):
                return flatten_cell(value[key])
        return ""
    return str(value).strip()


def _as_millis(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    number = int(text)
    if number >= 10**11:
        return number
    if 10**9 <= number < 10**11:
        return number * 1000
    return None


def value_matches_day(value: Any, day: str) -> bool:
    """单元格是否表示指定日。文本写法或当天时间戳都算。"""
    text = flatten_cell(value)
    if text in set(day_tokens(day)):
        return True
    millis = _as_millis(value if not isinstance(value, list) else text)
    if millis is None and text.isdigit():
        millis = _as_millis(text)
    if millis is None:
        return False
    start = shanghai_midnight_ms(day)
    return start <= millis < start + 86_400_000


def format_cell(value: Any) -> str:
    """把单元格格式化成页面上的一行文字。"""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    millis = _as_millis(value)
    if millis is not None and not isinstance(value, str):
        moment = datetime.datetime.fromtimestamp(millis / 1000, _CN_TZ)
        if (moment.hour, moment.minute, moment.second) == (0, 0, 0):
            return moment.strftime("%Y-%m-%d")
        return moment.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or "—"
    if isinstance(value, list):
        parts = [format_cell(item) for item in value]
        text = "、".join(part for part in parts if part and part != "—")
        return text or "—"
    if isinstance(value, dict):
        for key in ("text", "name", "link", "value"):
            if value.get(key) not in (None, ""):
                return format_cell(value[key])
        return "—"
    return str(value)
