"""短线盘面 · 板块人气排名（对齐 awam-stock MoodBlockItem）。

数据源：开盘啦 `RealRankingInfo`，`ZSType=7`（见 awam-stock 后端股票数据来源）。
涨停家数来自同站 `PlateAnalysis`（BlockDay），按板块 code 合并。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from . import trade_calendar
from .util import china_now

_TTL = 20.0
_OFFSESSION_TTL = 86400.0
_LIMIT = 30
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_LONGTOU = "https://apphq.longhuvip.com/w1/api/index.php"
# 开盘啦对浏览器 UA 会返回 errcode=0 但 list 空；须用 App UA（对齐 awam longTouPost）
_UA = {
    "User-Agent": "lhb/5.13.7 (com.kaipanla.www; build:0; iOS 16.1.0) Alamofire/4.9.1",
    "Accept": "*/*",
}


def _cached(key: str, ttl: float, build):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = build()
    if val is not None:
        with _lock:
            _cache[key] = (now, val)
    return val


def _num(v, default=None):
    try:
        if v in ("-", "", None):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _http_get_json(url: str) -> Any:
    import requests

    r = requests.get(url, headers=_UA, timeout=12)
    r.raise_for_status()
    return r.json()


def _parse_mood_row(item: Any, sort: int) -> Optional[dict]:
    """开盘啦 list 行 → MoodBlockItem 字段（下标对齐 moodBlockItemMap）。"""
    if not isinstance(item, (list, tuple)) or len(item) < 5:
        return None
    code = str(item[0]).strip() if item[0] is not None else ""
    name = str(item[1]).strip() if item[1] is not None else ""
    if not code or not name:
        return None
    power = _num(item[2])
    r = _num(item[3])
    rs = _num(item[4])
    m_net = _num(item[6]) if len(item) > 6 else None
    return {
        "code": code,
        "name": name,
        "power": int(power) if power is not None else None,
        "pct": r,          # 涨跌幅 %
        "speed": rs,       # 涨速 %
        "m_net": m_net,    # 主力净额，元
        "zt": None,        # 涨停家数，稍后合并
        "sort": sort,
    }


def _fetch_ranking(limit: int = _LIMIT) -> tuple[list[dict], Optional[int]]:
    """拉板块人气榜。返回 (rows, api_time)。"""
    url = (
        f"{_LONGTOU}?Order=1&a=RealRankingInfo&st={limit}"
        f"&apiv=w25&Type=1&c=ZhiShuRanking&PhoneOSNew=1&Index=0&ZSType=7&"
    )
    raw = _http_get_json(url)
    rows: list[dict] = []
    for i, item in enumerate(raw.get("list") or []):
        parsed = _parse_mood_row(item, sort=i + 1)
        if parsed:
            rows.append(parsed)
    api_time = raw.get("Time")
    try:
        api_time = int(api_time) if api_time is not None else None
    except (TypeError, ValueError):
        api_time = None
    return rows, api_time


def _fetch_zt_map() -> dict[str, int]:
    """板块涨停家数：PlateAnalysis Type=2，code→zt。"""
    url = (
        f"{_LONGTOU}?Order=1&a=PlateAnalysis&st=300&c=HomeDingPan"
        f"&PhoneOSNew=1&Index=0&PidType=0&apiv=w25&Type=2&"
    )
    try:
        raw = _http_get_json(url)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, int] = {}
    for item in raw.get("list") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        code = str(item[0]).strip()
        zt = _num(item[2])
        if code and zt is not None:
            out[code] = int(zt)
    return out


def snapshot(limit: int = _LIMIT) -> dict:
    """板块人气排名快照。"""

    def build():
        try:
            rows, api_time = _fetch_ranking(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "reason": f"开盘啦板块人气取数失败：{type(exc).__name__}",
                "blocks": [],
                "updated": china_now().strftime("%Y-%m-%d %H:%M"),
            }
        if rows:
            zt_map = _fetch_zt_map()
            if zt_map:
                for row in rows:
                    zt = zt_map.get(row["code"])
                    if zt is not None:
                        row["zt"] = zt
        available = bool(rows)
        return {
            "available": available,
            "reason": None if available else "板块人气暂无数据（非交易时段或开盘啦未返回）",
            "date": china_now().strftime("%Y-%m-%d"),
            "api_time": api_time,
            "blocks": rows,
            "updated": china_now().strftime("%Y-%m-%d %H:%M"),
        }

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    key = "mood_block:live" if live else f"mood_block:off:{trade_calendar.latest_session() or 'na'}"

    return _cached(key, ttl, build) or {
        "available": False,
        "reason": "板块人气取数失败",
        "blocks": [],
    }
