"""盘中昨涨停效应 —— 打板成功率开 / 连板溢价 / 涨停大跌数。

口径对齐复盘侧：
  · 打板成功率-开盘 = `emotion_metrics.money_effect.open_success_rate`
  · 连板溢价 = `emotion_metrics.consec_premium.avg`（昨 2 板+ 今日均涨幅）
  · 涨停大跌数 = `market_facts.loss_effect.deep_loss_5_count`（昨涨停今跌超 5%）

与 `live_emotion` 分接口（ADR-0001：派生指标不并进打板情绪）。

缓存分层（静态不随轮询重算）：
  · 静态：昨涨停名单、昨日连板数、开盘溢价、开盘成功率 —— 盘中长 TTL
  · 动态：今日涨跌幅 → 连板溢价 / 跌超 5% 家数 —— 短 TTL
"""

from __future__ import annotations

import json
import os
import threading
import time
from statistics import mean
from typing import Any, Optional

from . import paths as _paths
from . import trade_calendar
from .util import china_now

_STATIC_TTL = 3600.0
_DYNAMIC_TTL = 20.0
_CAL_TTL = 3600.0
_OFFSESSION_TTL = 86400.0

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_CACHE_DIR = ""

_ARCHIVE_KEYS = (
    "open_success_rate",
    "open_sample",
    "consec_premium_avg",
    "consec_premium_sample",
    "deep_loss_5_count",
    "deep_loss_5_rate",
    "sample",
)


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "live_zt_effect")


def _reset_runtime_state() -> None:
    """测试用：清空内存缓存。"""
    with _lock:
        _cache.clear()


def _cached(key: str, ttl: float, build):
    """极简 TTL 缓存。失败（None）不缓存；合法空结果要缓存。"""
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
    raw = _load_archive(prev)
    return {k: raw[k] for k in _ARCHIVE_KEYS if k in raw and raw[k] is not None}


def _fetch_universe(as_of: str) -> Optional[dict]:
    """昨涨停宇宙：代码 + 昨日连板数（及可选定稿涨跌幅）。

    优先东财「昨日涨停池」（含 prev_boards）；盘中只应通过静态缓存打一次。
    """
    from .data import fetch_prev_pool

    rows = fetch_prev_pool(as_of)
    if not rows:
        return None
    codes: list[str] = []
    boards: dict[str, int] = {}
    seed_rets: dict[str, float] = {}
    for r in rows:
        code = str(r.get("code") or "").zfill(6)
        if not code or code == "000000":
            continue
        codes.append(code)
        boards[code] = int(r.get("prev_boards") or 0)
        if r.get("ret") is not None:
            try:
                seed_rets[code] = float(r["ret"])
            except (TypeError, ValueError):
                pass
    if not codes:
        return None
    # 保序去重
    codes = list(dict.fromkeys(codes))
    return {"codes": codes, "boards": boards, "seed_rets": seed_rets}


def _build_static(as_of: str) -> Optional[dict]:
    """静态底座：名单 / 连板数 / 开盘溢价 / 开盘成功率。"""
    from .emotion_metrics import (
        _batch_open_gap_live,
        _success_rates,
        batch_open_gap,
    )

    univ = _fetch_universe(as_of)
    if univ is None:
        return None
    codes: list[str] = univ["codes"]
    boards: dict[str, int] = univ["boards"]
    # 盘中 batch_open_gap 会被 live_quotes_are_close_of 挡掉再退回慢速日 K；
    # 开盘溢价盘中用 L1 即可，且开盘后不再变，适合静态缓存。
    if trade_calendar.is_settled(as_of):
        open_gaps = batch_open_gap(codes, as_of)
    else:
        open_gaps = _batch_open_gap_live(codes)
        if not open_gaps:
            open_gaps = batch_open_gap(codes, as_of)
    open_vals = [open_gaps[c] for c in codes if open_gaps.get(c) is not None]
    rates = _success_rates([], open_vals)
    return {
        "codes": codes,
        "boards": boards,
        "seed_rets": univ.get("seed_rets") or {},
        "open_gaps": open_gaps,
        "open_success_rate": rates.get("open_success_rate"),
        "open_sample": rates.get("open_sample") or 0,
        "sample": len(codes),
    }


def _fetch_rets(codes: list[str], seed: dict[str, float]) -> dict[str, float]:
    """动态涨跌幅：腾讯批量；失败时回退静态种子（东财池首刷带的 ret）。"""
    from .emotion_metrics import batch_pct

    if not codes:
        return {}
    pct = batch_pct(codes)
    if pct:
        return pct
    return dict(seed)


def _metrics_from(static: dict, rets: dict[str, float]) -> dict[str, Any]:
    codes: list[str] = static["codes"]
    boards: dict[str, int] = static["boards"]
    vals = [rets[c] for c in codes if c in rets]
    n = len(vals)

    hi_codes = [c for c in codes if (boards.get(c) or 0) >= 2]
    hi_vals = [rets[c] for c in hi_codes if c in rets]
    consec_avg = round(mean(hi_vals), 2) if hi_vals else None
    deep5 = sum(1 for v in vals if v <= -5) if vals else None
    deep5_rate = round(deep5 / n, 3) if n and deep5 is not None else None

    return {
        "open_success_rate": static.get("open_success_rate"),
        "open_sample": static.get("open_sample") or 0,
        "consec_premium_avg": consec_avg,
        "consec_premium_sample": len(hi_vals),
        "deep_loss_5_count": deep5,
        "deep_loss_5_rate": deep5_rate,
        "sample": static.get("sample") or len(codes),
        "ret_sample": n,
    }


def snapshot(as_of: str | None = None) -> dict:
    """昨涨停效应快照。非交易时段优先读归档 / 定稿静态结果。"""
    calendar_today = china_now().strftime("%Y-%m-%d")

    if as_of is None:
        as_of, prev_day, is_live = _cached(
            f"asof:{calendar_today}", _CAL_TTL,
            lambda: trade_calendar.resolve_as_of(calendar_today),
        )
    else:
        prev_day = _cached(
            f"prevday:{as_of}", _CAL_TTL,
            lambda: trade_calendar.prev_trade_date(as_of),
        )
        if prev_day and prev_day >= as_of:
            prev_day = None
        is_live = as_of == calendar_today

    yesterday = _yesterday_slice(prev_day)

    # 非实时场次：有归档则直接返回，避免周末反复打东财 / 腾讯
    if not is_live:
        archived = _load_archive(as_of)
        if archived and any(k in archived for k in _ARCHIVE_KEYS):
            out = {
                "available": True,
                "date": as_of,
                "as_of": china_now().strftime("%H:%M"),
                "phase": "非交易日",
                "is_live": False,
                "prev_date": prev_day,
                "yesterday": yesterday,
                "from_archive": True,
                "source": "archive",
            }
            for k in _ARCHIVE_KEYS:
                if k in archived:
                    out[k] = archived[k]
            return _cached(f"zt_effect:arch:{as_of}", _OFFSESSION_TTL, lambda: out)

    settled = _cached(
        f"settled:{as_of}", _CAL_TTL,
        lambda: ("Y" if trade_calendar.is_settled(as_of) else "N"),
    ) == "Y"
    static_ttl = _OFFSESSION_TTL if (settled or not is_live) else _STATIC_TTL
    dyn_ttl = _OFFSESSION_TTL if (settled or not is_live) else _DYNAMIC_TTL

    static = _cached(f"static:{as_of}", static_ttl, lambda: _build_static(as_of))
    if static is None:
        return {
            "available": False,
            "reason": "昨涨停池取数失败",
            "date": as_of,
            "prev_date": prev_day,
            "is_live": is_live,
            "yesterday": yesterday,
        }

    codes: list[str] = static["codes"]
    seed: dict[str, float] = static.get("seed_rets") or {}

    # 已定稿：涨跌幅不再变，直接用宇宙种子（fetch_prev_pool 落盘），勿反复 batch_pct
    if settled and seed:
        rets = seed
    else:
        rets = _cached(
            f"rets:{as_of}", dyn_ttl,
            lambda: _fetch_rets(codes, seed),
        ) or {}

    metrics = _metrics_from(static, rets)
    # 动态样本过少时仍可报开盘成功率（静态），连板溢价 / 大跌数标不可用片段
    has_open = metrics.get("open_success_rate") is not None
    has_dyn = (metrics.get("ret_sample") or 0) > 0
    available = has_open or has_dyn

    if not is_live:
        phase = "非交易日"
    elif settled:
        phase = "已收盘"
    else:
        phase = "盘中"

    out = {
        "available": available,
        "reason": None if available else "昨涨停效应暂不可用",
        "date": as_of,
        "as_of": china_now().strftime("%H:%M"),
        "phase": phase,
        "is_live": is_live,
        "prev_date": prev_day,
        "source": "settled" if settled else "live",
        **metrics,
        "yesterday": yesterday,
    }

    if is_live and trade_calendar.should_write_daily_cache(as_of) and available:
        _save_archive(as_of, out)
    return out
