"""今日**实时**打板情绪（盘面数据页用）。

和 `emotion_metrics` 的分工：
  · `emotion_metrics` = 复盘口径，要当天的**收盘**数据，只算已收盘那一场；
  · 这里 = 盘中快照，回答"此刻打板好不好做"，数字随盘变化。

⚠️ 为什么不复用 `vr/` 的 `/api/market/emotion`：那条被
   `server._pin_pool_to_settled_session()` 锁在已收盘那一场了（复盘类块需要），
   而这里恰恰要今天。所以走那个锁留下的未加锁出口 `_pool_unpinned`。

⚠️ 炸板率必须**另取炸板池**：涨停池里的 `zbc` 只是"这一只炸过几次"，
   全市场炸了多少家它答不了。分母 = 最终封住 + 炸板未回封 = 尝试过涨停的家数。

「今日 / 昨日」对照按**数据场次**锚定：
  · 有今日涨停池 → 左侧=今天，右侧=前一交易日归档；
  · 无今日池（周末 / 盘前）→ 回退到行情所属场次（如周五），对照其前一交易日（周四），
    仍展示「最近两场」对比，而不是空卡或自己比自己。
  · 归档只在「日历今天 == 场次」时写入；禁止把周五数据存成周六.json。
晋级率一并归档，便于与封板率 / 炸板率等同屏对照。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Optional

from . import trade_calendar
from .util import china_now

# 取一次要打四个池（涨停/炸板/跌停/昨日涨停），实测约 8 秒 ——
# 而界面是 5 秒一刷，不缓存就会请求叠着堆（日志里能看到并发好几条），
# 既拖慢页面又白撞东财的限流。
#
# 分两档：**昨日的池子盘中不会变**，缓存到当天结束都行；今日的池子缓存 15 秒
# （比 5 秒的刷新间隔长一点，够挡住叠加；行情本身也不值得更细）。
# ⚠️ `trade_calendar.prev_trade_date` / `is_settled` **每次调用都打网络**
#    （各约 1.7-3.2 秒，那边自己没缓存）。只缓存四个池子的话，热态还是要 3.9 秒 ——
#    比 5 秒的刷新间隔差不了多少，等于没修。日历结果一天内不会变，一起缓存掉。
_TODAY_TTL = 15.0
_PREV_TTL = 3600.0
_CAL_TTL = 3600.0
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/live_emotion")
# 写入归档的字段（不含 date / as_of 等元数据）
_ARCHIVE_KEYS = (
    "zt_count", "dt_count", "zb_count", "max_boards", "lianban_count",
    "seal_rate", "break_rate", "promotion_rate", "promotion_base",
)


_MISS = object()


def _cached(key: str, ttl: float, build):
    """极简 TTL 缓存。**失败不缓存**（下次重试），但「空但有效」要缓存。

    ⚠️ 判据必须是 `is not None`，不能写 `if val:` —— 那会把**合法的空结果**
    当成失败：今天跌停 0 家时 `dt` 是 `[]`，用真值判断就永不入缓存，
    每次请求都重打一次网络（实测热态因此卡在 1.78 秒，等于没缓存）。
    取数失败时 `_pool` 返回 None，两者本来就能区分。
    """
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


def _pool(kind: str, ymd: str) -> Optional[list[dict]]:
    """取东财涨停板四池之一。走未加锁出口；拿不到返回 None（不把失败当成 0 家）。"""
    astock = sys.modules.get("astock")
    if astock is None:
        return None
    fetch = getattr(astock, "_pool_unpinned", None) or getattr(astock, "em_zt_topic_pool", None)
    if fetch is None:
        return None
    try:
        return fetch(kind, ymd, "fbt:asc") or []
    except Exception:  # noqa: BLE001  取不到就整块标不可用
        return None


def _rate(hit: int, total: int) -> Optional[float]:
    return round(hit / total, 4) if total else None


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


def _save_archive(date: str, env: dict) -> None:
    """盘中也写：收盘后最后一次覆盖即为「昨日」对照。失败静默。"""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        payload = {k: env.get(k) for k in _ARCHIVE_KEYS if env.get(k) is not None}
        payload["date"] = date
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def _yesterday_slice(prev: str | None) -> dict[str, Any]:
    """从上一交易日归档取出对照字段；无归档返回空 dict（前端显示 /-）。"""
    raw = _load_archive(prev)
    return {k: raw[k] for k in _ARCHIVE_KEYS if k in raw and raw[k] is not None}


def _metrics_from_pools(
    zt: list[dict],
    zb: Optional[list[dict]],
    dt: Optional[list[dict]],
    prev_zt: Optional[list[dict]],
) -> dict[str, Any]:
    """由涨停/炸板/跌停池算出对照用指标（不含日期元数据）。"""
    boards = [int(p.get("lbc") or 1) for p in zt]
    zt_n, zb_n = len(zt), (len(zb) if zb is not None else None)
    tried = zt_n + zb_n if zb_n is not None else None
    today_codes = {str(p.get("c")) for p in zt}
    promo: Optional[float] = None
    promo_base: Optional[int] = None
    if prev_zt:
        promo_base = len(prev_zt)
        promo = _rate(sum(1 for p in prev_zt if str(p.get("c")) in today_codes), promo_base)
    return {
        "zt_count": zt_n,
        "dt_count": len(dt) if dt is not None else None,
        "zb_count": zb_n,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": sum(1 for b in boards if b >= 2),
        "seal_rate": _rate(zt_n, tried) if tried else None,
        "break_rate": _rate(zb_n, tried) if (tried and zb_n is not None) else None,
        "promotion_rate": promo,
        "promotion_base": promo_base,
    }


def _resolve_as_of(calendar_today: str) -> tuple[str, bool]:
    """锚定左侧场次。

    返回 (as_of, is_live)。`is_live` 仅当行情所属场次就是日历今天 ——
    周末/盘前东财常把上一场涨停池填进「今天」的请求日，池非空也不算 live。
    """
    from .util import is_weekend

    qd = trade_calendar.quote_trade_day()
    latest = trade_calendar.latest_session()
    if qd and qd <= calendar_today:
        return qd, qd == calendar_today
    if latest and latest <= calendar_today:
        return latest, latest == calendar_today
    if is_weekend(calendar_today):
        return (latest or calendar_today), False
    return calendar_today, True


def snapshot() -> dict:
    """打板情绪快照。非交易时段回退到最近场次，仍给出「最近两场」对照。

    成功时附带 `yesterday`（对照场次归档）与 `prev_date`。
    """
    calendar_today = china_now().strftime("%Y-%m-%d")

    def _as_of_pair() -> tuple[str, bool]:
        return _cached(f"asof:{calendar_today}", _CAL_TTL,
                       lambda: _resolve_as_of(calendar_today))

    def _prev_of(day: str) -> str | None:
        return _cached(f"prevday:{day}", _CAL_TTL,
                       lambda: trade_calendar.prev_trade_date(day))

    as_of, is_live = _as_of_pair()
    prev_day = _prev_of(as_of)
    if prev_day and prev_day >= as_of:
        prev_day = None

    # 取池：live 用日历今天；否则强制按 as_of 取（忽略「周末请求日仍非空」的假今日池）
    pool_day = calendar_today if is_live else as_of
    pool_ymd = pool_day.replace("-", "")
    pool_ttl = _TODAY_TTL if is_live else _PREV_TTL

    zt = _cached(f"zt:{pool_ymd}", pool_ttl, lambda: _pool("getTopicZTPool", pool_ymd))
    if zt is None:
        return {"available": False, "reason": "涨停池取数失败",
                "date": as_of, "prev_date": prev_day,
                "is_live": is_live, "yesterday": _yesterday_slice(prev_day)}

    if not zt:
        if is_live:
            return {"available": False, "date": calendar_today,
                    "reason": "今日还没有涨停池（未开盘 / 非交易日）",
                    "prev_date": prev_day, "is_live": False,
                    "yesterday": _yesterday_slice(prev_day)}
        # 非 live 且 as_of 池空 → 试本地归档撑左侧
        archived = _load_archive(as_of)
        if not archived:
            return {"available": False, "date": as_of,
                    "reason": "最近场次无涨停池也无归档",
                    "prev_date": prev_day, "is_live": False,
                    "yesterday": _yesterday_slice(prev_day)}
        out = {
            "available": True,
            "date": as_of,
            "as_of": china_now().strftime("%H:%M"),
            "phase": "非交易日",
            "is_live": False,
            "prev_date": prev_day,
            "promotion_base_date": prev_day,
            "yesterday": _yesterday_slice(prev_day),
        }
        for k in _ARCHIVE_KEYS:
            if k in archived:
                out[k] = archived[k]
        return out

    settled = _cached(f"settled:{as_of}", _CAL_TTL,
                      lambda: ("Y" if trade_calendar.is_settled(as_of) else "N")) == "Y"

    zb = _cached(f"zb:{pool_ymd}", pool_ttl, lambda: _pool("getTopicZBPool", pool_ymd))
    dt = _cached(f"dt:{pool_ymd}", pool_ttl, lambda: _pool("getTopicDTPool", pool_ymd))
    prev_zt = (_cached(f"zt:{prev_day}", _PREV_TTL,
                       lambda: _pool("getTopicZTPool", prev_day.replace("-", "")))
               if prev_day else None)

    metrics = _metrics_from_pools(zt, zb, dt, prev_zt)

    if not is_live:
        phase = "非交易日"
    elif settled:
        phase = "已收盘"
    else:
        phase = "盘中"

    out = {
        "available": True,
        "date": as_of,
        "as_of": china_now().strftime("%H:%M"),
        "phase": phase,
        "is_live": is_live,
        **metrics,
        # 分母是哪一场 —— 界面上两张卡都叫「晋级率」，把日期写死以免混淆
        "promotion_base_date": prev_day,
        "prev_date": prev_day,
        "yesterday": _yesterday_slice(prev_day),
    }
    # 只有日历今天这场才写归档，禁止周末把周五存成周六.json
    if is_live:
        _save_archive(as_of, out)
    return out
