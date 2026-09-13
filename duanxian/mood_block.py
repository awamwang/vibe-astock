"""短线盘面 · 板块人气排名（对齐 awam-stock MoodBlockItem）。

数据源：开盘啦 `RealRankingInfo`，`ZSType=7`（见 awam-stock 后端股票数据来源）。
涨停家数来自同站 `PlateAnalysis`（BlockDay），按板块 code 合并。

指定板块：`GetPlate_Info_QJ` + `PlateID`；历史日走 ``apphis`` 并带 `Date`。
定稿榜单按日落盘到 ``cache/mood_block/{date}.json``，供昨今对比复用。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from . import paths as _paths
from . import trade_calendar
from .util import china_now

_TTL = 20.0
_OFFSESSION_TTL = 86400.0
_LIMIT = 30
_RANK_PAGES = 5  # 每页 st=30，用于名称索引与人气筛选
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_CACHE_DIR = ""
_LONGTOU_HQ = "https://apphq.longhuvip.com/w1/api/index.php"
_LONGTOU_HIS = "https://apphis.longhuvip.com/w1/api/index.php"
# 开盘啦对浏览器 UA 会返回 errcode=0 但 list 空；须用 App UA（对齐 awam longTouPost）
_UA = {
    "User-Agent": "lhb/5.13.7 (com.kaipanla.www; build:0; iOS 16.1.0) Alamofire/4.9.1",
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "mood_block")


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


def _http_post_json(url: str, data: dict[str, Any]) -> Any:
    import requests

    r = requests.post(url, data=data, headers=_UA, timeout=12)
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


def _parse_plate_info_list(lst: Any, *, dated: bool) -> Optional[dict]:
    """GetPlate_Info_QJ 的 List → 统一字段。

    历史 ``apphis`` + Date：``[排名, 人气, 成交额, 主力净额, 涨幅, …]``。
    盘中 ``apphq`` 无 Date 时下标 4 不一定是涨幅，故 ``dated=False`` 时不采 pct。
    涨停家数不从此接口取（List[5] 对概念码常为 0），统一走 PlateAnalysis。
    """
    if not isinstance(lst, (list, tuple)) or len(lst) < 2:
        return None
    sort = _num(lst[0])
    power = _num(lst[1])
    amount = _num(lst[2]) if len(lst) > 2 else None
    m_net = _num(lst[3]) if len(lst) > 3 else None
    pct = None
    if len(lst) > 4:
        v4 = _num(lst[4])
        if dated and v4 is not None:
            pct = v4
        elif v4 is not None and abs(v4) <= 30:
            # 保守：数值像涨幅时才采用
            pct = v4
    return {
        "sort": int(sort) if sort is not None else None,
        "power": int(power) if power is not None else None,
        "amount": amount,
        "m_net": m_net,
        "pct": pct,
        "zt": None,
    }


def _fetch_ranking(limit: int = _LIMIT) -> tuple[list[dict], Optional[int]]:
    """拉板块人气榜（实时域）。返回 (rows, api_time)。"""
    url = (
        f"{_LONGTOU_HQ}?Order=1&a=RealRankingInfo&st={limit}"
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


def _fetch_ranking_pages(
    *,
    date: str | None = None,
    pages: int = _RANK_PAGES,
    page_size: int = _LIMIT,
) -> tuple[list[dict], Optional[int]]:
    """分页拉人气榜；``date`` 有值时走历史域并落盘复用。"""
    rows: list[dict] = []
    api_time: Optional[int] = None
    seen: set[str] = set()
    for page in range(max(1, pages)):
        index = page * page_size
        if date:
            raw = _http_post_json(_LONGTOU_HIS, {
                "a": "RealRankingInfo",
                "c": "ZhiShuRanking",
                "Order": "1",
                "st": str(page_size),
                "Type": "1",
                "Index": str(index),
                "ZSType": "7",
                "Date": date,
                "apiv": "w25",
                "PhoneOSNew": "1",
            })
        else:
            url = (
                f"{_LONGTOU_HQ}?Order=1&a=RealRankingInfo&st={page_size}"
                f"&apiv=w25&Type=1&c=ZhiShuRanking&PhoneOSNew=1"
                f"&Index={index}&ZSType=7&"
            )
            raw = _http_get_json(url)
        batch = raw.get("list") or []
        if not batch:
            break
        t = raw.get("Time")
        try:
            api_time = int(t) if t is not None else api_time
        except (TypeError, ValueError):
            pass
        for i, item in enumerate(batch):
            parsed = _parse_mood_row(item, sort=index + i + 1)
            if not parsed:
                continue
            if parsed["code"] in seen:
                continue
            seen.add(parsed["code"])
            rows.append(parsed)
        if len(batch) < page_size:
            break
    return rows, api_time


def _fetch_zt_map_pid(pid_type: int, *, page_size: int = 100, max_pages: int = 8) -> dict[str, int]:
    """PlateAnalysis Type=2 单 PidType 分页 → code→zt。"""
    out: dict[str, int] = {}
    for page in range(max(1, max_pages)):
        index = page * page_size
        url = (
            f"{_LONGTOU_HQ}?Order=1&a=PlateAnalysis&st={page_size}&c=HomeDingPan"
            f"&PhoneOSNew=1&Index={index}&PidType={pid_type}&apiv=w25&Type=2&"
        )
        try:
            raw = _http_get_json(url)
        except Exception:  # noqa: BLE001
            break
        batch = raw.get("list") or []
        if not batch:
            break
        for item in batch:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            code = str(item[0]).strip()
            zt = _num(item[2])
            if not code or zt is None:
                continue
            zti = int(zt)
            prev = out.get(code)
            out[code] = zti if prev is None else max(prev, zti)
        if len(batch) < page_size:
            break
    return out


def fetch_zt_map() -> dict[str, int]:
    """板块涨停家数（开盘啦 PlateAnalysis Type=2）。

    合并 PidType=0/1/2：覆盖 80xxxx 结构码与 885xxx 概念码（如 PCB概念）。
    结果带短 TTL 缓存。
    """

    def build():
        out: dict[str, int] = {}
        for pid in (0, 1, 2):
            part = _fetch_zt_map_pid(pid)
            for code, zt in part.items():
                prev = out.get(code)
                out[code] = zt if prev is None else max(prev, zt)
        return out

    return _cached("mood_zt_map:live", _TTL if trade_calendar.is_calendar_session_live() else _OFFSESSION_TTL, build) or {}


def _fetch_zt_map() -> dict[str, int]:
    """兼容旧名。"""
    return fetch_zt_map()


def _zt_archive_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}_zt.json")


def _load_zt_archive(date: str | None) -> dict[str, int]:
    if not date:
        return {}
    path = _zt_archive_path(date)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("zt") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return out
    except Exception:  # noqa: BLE001
        return {}


def _save_zt_archive(date: str, zt_map: dict[str, int]) -> None:
    if not date or not zt_map or not trade_calendar.should_write_daily_cache(date):
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _zt_archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"date": date, "zt": zt_map}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def zt_map_for_date(date: str | None) -> dict[str, int]:
    """指定场次涨停家数：定稿日优先读盘；当日/最近场次拉 PlateAnalysis 并可落盘。"""
    date_s = str(date or "").strip()
    if not date_s:
        return {}
    archived = _load_zt_archive(date_s)
    if archived:
        return archived
    latest = trade_calendar.latest_session()
    # 历史接口不稳定；仅对最近场次拉 live PlateAnalysis
    if date_s != latest and date_s != china_now().strftime("%Y-%m-%d"):
        return {}
    live = fetch_zt_map()
    if live and date_s == latest:
        _save_zt_archive(date_s, live)
    return live


def _archive_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _load_archive(date: str | None) -> dict:
    if not date:
        return {}
    path = _archive_path(date)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_archive(date: str, payload: dict) -> None:
    """定稿榜单落盘；失败静默。"""
    if not date or not trade_calendar.should_write_daily_cache(date):
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        body = {k: v for k, v in payload.items() if v is not None}
        body["date"] = date
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def ranking_for_date(date: str, *, force: bool = False) -> dict:
    """指定交易日人气榜定稿：优先读盘，否则拉历史域并落盘。

    返回 ``{date, available, blocks, from_archive, api_time, reason?}``。
    """
    date_s = str(date or "").strip()
    if not date_s:
        return {
            "date": date_s,
            "available": False,
            "blocks": [],
            "from_archive": False,
            "reason": "缺少日期",
        }

    def build():
        if not force:
            archived = _load_archive(date_s)
            blocks = archived.get("blocks")
            if isinstance(blocks, list) and blocks:
                return {
                    "date": date_s,
                    "available": True,
                    "blocks": blocks,
                    "from_archive": True,
                    "api_time": archived.get("api_time"),
                    "reason": None,
                }
        try:
            rows, api_time = _fetch_ranking_pages(date=date_s)
        except Exception as exc:  # noqa: BLE001
            return {
                "date": date_s,
                "available": False,
                "blocks": [],
                "from_archive": False,
                "reason": f"历史人气榜取数失败：{type(exc).__name__}",
            }
        if rows:
            zt_map = zt_map_for_date(date_s)
            if zt_map:
                for row in rows:
                    zt = zt_map.get(row["code"])
                    if zt is not None:
                        row["zt"] = zt
            out = {
                "date": date_s,
                "available": True,
                "blocks": rows,
                "from_archive": False,
                "api_time": api_time,
                "reason": None,
            }
            _save_archive(date_s, out)
            return out
        return {
            "date": date_s,
            "available": False,
            "blocks": [],
            "from_archive": False,
            "reason": "历史人气榜暂无数据",
        }

    # 定稿日：长 TTL；强制刷新绕过内存缓存但仍可读盘
    ttl = _OFFSESSION_TTL if trade_calendar.is_settled(date_s) else _TTL
    key = f"mood_rank:{date_s}:{'f' if force else 'n'}"
    return _cached(key, ttl, build) or {
        "date": date_s,
        "available": False,
        "blocks": [],
        "from_archive": False,
        "reason": "历史人气榜取数失败",
    }


def plate_info(code: str, *, date: str | None = None) -> Optional[dict]:
    """指定板块点查（GetPlate_Info_QJ）。

    ``date`` 为空：实时域；有值：历史域 + Date。
    返回 ``{code, date, power, pct, m_net, amount, sort}``（不含涨停；涨停见 ``zt_map_for_date``）。
    """
    code_s = str(code or "").strip()
    if not code_s:
        return None
    date_s = str(date or "").strip() or None

    def build():
        try:
            if date_s:
                raw = _http_post_json(_LONGTOU_HIS, {
                    "a": "GetPlate_Info_QJ",
                    "c": "ZhiShuRanking",
                    "PlateID": code_s,
                    "Date": date_s,
                    "apiv": "w25",
                    "PhoneOSNew": "1",
                })
                dated = True
            else:
                raw = _http_get_json(
                    f"{_LONGTOU_HQ}?a=GetPlate_Info_QJ&c=ZhiShuRanking"
                    f"&PlateID={code_s}&apiv=w25&PhoneOSNew=1&"
                )
                dated = False
        except Exception:  # noqa: BLE001
            return None
        parsed = _parse_plate_info_list(raw.get("List"), dated=dated)
        if not parsed:
            return None
        resp_date = str(raw.get("Date") or date_s or "").strip() or None
        return {
            "code": code_s,
            "date": resp_date,
            **parsed,
        }

    ttl = _OFFSESSION_TTL if date_s and trade_calendar.is_settled(date_s) else _TTL
    key = f"mood_plate:{code_s}:{date_s or 'live'}"
    return _cached(key, ttl, build)


def fetch_ranking_catalog(*, date: str | None = None, pages: int | None = None) -> list[dict]:
    """分页拉人气榜作名称索引；失败返回空列表。"""
    try:
        rows, _ = _fetch_ranking_pages(date=date, pages=pages or _RANK_PAGES)
        return rows
    except Exception:  # noqa: BLE001
        return []


def snapshot(limit: int = _LIMIT) -> dict:
    """板块人气排名快照。"""

    def build():
        try:
            rows, api_time = _fetch_ranking(limit=limit)
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "reason": f"板块人气取数失败：{type(exc).__name__}",
                "blocks": [],
                "updated": china_now().strftime("%Y-%m-%d %H:%M"),
            }
        zt_map: dict[str, int] = {}
        if rows:
            zt_map = fetch_zt_map()
            if zt_map:
                for row in rows:
                    zt = zt_map.get(row["code"])
                    if zt is not None:
                        row["zt"] = zt
        available = bool(rows)
        as_of = trade_calendar.latest_session() or china_now().strftime("%Y-%m-%d")
        out = {
            "available": available,
            "reason": None if available else "板块人气暂无数据（非交易时段或未返回）",
            "date": as_of,
            "api_time": api_time,
            "blocks": rows,
            "updated": china_now().strftime("%Y-%m-%d %H:%M"),
        }
        if available and trade_calendar.should_write_daily_cache(as_of):
            # 实时榜定稿窗内同步落盘，供次日昨对比复用
            archive_blocks = rows
            try:
                wide = fetch_ranking_catalog(date=None)
                if wide:
                    archive_blocks = wide
                    if zt_map:
                        for row in archive_blocks:
                            zt = zt_map.get(row["code"])
                            if zt is not None:
                                row["zt"] = zt
            except Exception:  # noqa: BLE001
                pass
            _save_archive(as_of, {
                "date": as_of,
                "available": True,
                "blocks": archive_blocks,
                "api_time": api_time,
                "from_archive": False,
            })
            if zt_map:
                _save_zt_archive(as_of, zt_map)
        return out

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    key = "mood_block:live" if live else f"mood_block:off:{trade_calendar.latest_session() or 'na'}"

    return _cached(key, ttl, build) or {
        "available": False,
        "reason": "板块人气取数失败",
        "blocks": [],
    }
