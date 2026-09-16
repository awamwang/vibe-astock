"""打板情绪共振 —— 六层相对十日基线的同向分数。

产品页是「短线共振」；本模块只算其中打板情绪共振这一块。
不接情绪周期、不定 Cap。合成是纯函数；取数在 `snapshot`。
"""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
import time
from typing import Any, Optional

from . import paths as _paths
from . import trade_calendar
from .util import atomic_write_json, china_now

# 随盘 15s：短线盘面 10s 一刷，比间隔长才挡得住叠请求（同 live_emotion）。
# 定稿场次对照窗不会变，缓存到进程内一天。
_LIVE_TTL = 15.0
_SETTLED_TTL = 86400.0
_CAL_TTL = 3600.0
_INFLIGHT_WAIT = 120.0

_gather_cache: dict[str, tuple[float, dict, float]] = {}
_day_mem: dict[str, tuple[float, dict, float]] = {}
_cal_cache: dict[str, tuple[float, object]] = {}
_inflight: dict[str, threading.Event] = {}
_snap_lock = threading.Lock()

_CACHE_DIR = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "board_emotion_resonance")


def _reset_runtime_state() -> None:
    """测试用：丢掉内存缓存；磁盘归档由测试 monkeypatch 目录。"""
    with _snap_lock:
        _gather_cache.clear()
        _day_mem.clear()
        _cal_cache.clear()
        _inflight.clear()

LOOKBACK = 10
MIN_BASELINE_N = 5
MIN_ACTIVE_LAYERS = 4
DEFAULT_WEIGHT = 100.0
LABEL_BAND = 0.25
SIGMA_EPS = 1e-12

# invert=True：原值越高越负（炸板、深亏）
LAYERS: tuple[dict[str, Any], ...] = (
    {"key": "max_boards", "label": "最高连板", "invert": False, "unit": "板"},
    {"key": "promotion_rate", "label": "晋级率", "invert": False, "unit": "ratio"},
    {"key": "break_rate", "label": "炸板率", "invert": True, "unit": "ratio"},
    {"key": "zt_minus_dt", "label": "涨停相对跌停", "invert": False, "unit": "count"},
    {"key": "money_avg", "label": "赚钱效应均", "invert": False, "unit": "pct"},
    {"key": "deep_loss_5_rate", "label": "深亏占比", "invert": True, "unit": "ratio"},
)

LAYER_KEYS: tuple[str, ...] = tuple(s["key"] for s in LAYERS)
_LAYER_BY_KEY = {s["key"]: s for s in LAYERS}


def _cached(key: str, ttl: float, build):
    """失败（None）不缓存；空列表等假值要缓存。锁外 build。"""
    now = time.monotonic()
    with _snap_lock:
        hit = _cal_cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = build()
    if val is not None:
        with _snap_lock:
            _cal_cache[key] = (now, val)
    return val


def _today() -> str:
    return china_now().strftime("%Y-%m-%d")


def _date_is_settled(date: str) -> bool:
    today = _today()
    if date < today:
        return True
    if date > today:
        return False
    return _cached(
        f"settled:{date}", _CAL_TTL,
        lambda: "Y" if trade_calendar.is_settled(date) else "N",
    ) == "Y"


def _archive_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _load_day(date: str) -> dict:
    path = _archive_path(date)
    if not _CACHE_DIR or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_day(date: str, payload: dict) -> None:
    if not _CACHE_DIR:
        return
    atomic_write_json(_archive_path(date), payload)


def _day_complete(arch: dict) -> bool:
    return all(k in arch for k in LAYER_KEYS)


def _layers_from_arch(arch: dict) -> dict[str, Optional[float]]:
    return {k: _f(arch.get(k)) for k in LAYER_KEYS}


def _remember_day(date: str, readings: dict[str, Optional[float]], ttl: float) -> None:
    with _snap_lock:
        _day_mem[date] = (time.monotonic(), dict(readings), ttl)


def _f(v: Any) -> Optional[float]:
    if v is None or v is False:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def coefficient(value: Optional[float], baseline: Optional[float],
                sigma: Optional[float], invert: bool) -> Optional[float]:
    """当场读数相对基线、按 σ 压到 (-1, 1)。σ≈0 则系数为 0（不是缺失）。"""
    if value is None or baseline is None:
        return None
    if sigma is None or sigma < SIGMA_EPS:
        return 0.0
    z = (value - baseline) / sigma
    if invert:
        z = -z
    return round(math.tanh(z), 6)


def mean_sigma(values: list[float]) -> tuple[Optional[float], float, int]:
    """返回 (均值, σ, n)。n<2 时 σ=0；调用方再用 n 判对照是否够。"""
    clean = [v for v in values if v is not None]
    n = len(clean)
    if n == 0:
        return None, 0.0, 0
    mu = statistics.fmean(clean)
    sig = statistics.stdev(clean) if n >= 2 else 0.0
    return mu, sig, n


def weak_label(score: Optional[float]) -> str:
    if score is None:
        return "不足"
    if score >= LABEL_BAND:
        return "偏多"
    if score <= -LABEL_BAND:
        return "偏空"
    return "混杂"


def _weight_of(weights: Optional[dict[str, Any]], key: str) -> float:
    if not weights or key not in weights:
        return DEFAULT_WEIGHT
    w = _f(weights[key])
    if w is None:
        return DEFAULT_WEIGHT
    return w


def score_board_emotion(
    current: dict[str, Optional[float]],
    window: dict[str, list[Optional[float]]],
    window_dates: list[str],
    *,
    weights: Optional[dict[str, Any]] = None,
    baselines: Optional[dict[str, Any]] = None,
    trial: bool = False,
) -> dict[str, Any]:
    """用当场读数 + 各层对照窗合成打板情绪共振。缺数不补。"""
    layers_out: list[dict[str, Any]] = []
    num = 0.0
    den = 0.0
    active = 0

    for spec in LAYERS:
        key = spec["key"]
        series = list(window.get(key) or [])
        if len(series) < len(window_dates):
            series = series + [None] * (len(window_dates) - len(series))
        series = series[:len(window_dates)]
        present = [v for v in series if v is not None]
        mu, sig, n = mean_sigma(present)
        missing_dates = [
            d for d, v in zip(window_dates, series) if v is None
        ]
        override = _f((baselines or {}).get(key)) if baselines else None
        baseline = override if override is not None else mu
        value = _f(current.get(key))
        w = _weight_of(weights, key)
        reasons: list[str] = []
        if value is None:
            reasons.append("当场缺失")
        if n < MIN_BASELINE_N:
            reasons.append(f"对照不足（{n}/{MIN_BASELINE_N}）")
        if missing_dates:
            reasons.append("对照缺 " + "、".join(missing_dates))
        if w <= 0:
            reasons.append("权重为 0，不参加合成")

        coeff = None
        included = False
        if value is not None and baseline is not None and n >= MIN_BASELINE_N and w > 0:
            coeff = coefficient(value, baseline, sig, spec["invert"])
            if coeff is not None:
                included = True
                num += w * coeff
                den += w
                active += 1

        diff = None
        if value is not None and baseline is not None:
            diff = round(value - baseline, 6)

        layers_out.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            "invert": spec["invert"],
            "value": value,
            "window_dates": list(window_dates),
            "window_values": series,
            "missing_dates": missing_dates,
            "n": n,
            "baseline_default": None if mu is None else round(mu, 6),
            "baseline": None if baseline is None else round(baseline, 6),
            "baseline_overridden": override is not None,
            "sigma": round(sig, 6),
            "diff": diff,
            "coefficient": coeff,
            "weight_default": DEFAULT_WEIGHT,
            "weight": w,
            "included": included,
            "missing": bool(reasons),
            "missing_reasons": reasons,
        })

    score = None
    reason = None
    if active < MIN_ACTIVE_LAYERS:
        reason = f"有效层 {active}/{MIN_ACTIVE_LAYERS}，整场不足"
    elif den <= 0:
        reason = "没有可合成的层"
    else:
        score = round(num / den, 6)

    return {
        "trial": trial,
        "score": score,
        "label": weak_label(score),
        "reason": reason,
        "active_layers": active,
        "layers": layers_out,
    }


def baseline_dates(as_of: str, n: int = LOOKBACK) -> list[str]:
    """近 n 个已定稿场次，不含本场。日历查询进程内缓存。"""
    cached = _cached(
        f"baseline:{as_of}:{n}",
        _CAL_TTL,
        lambda: _baseline_dates_uncached(as_of, n),
    )
    return list(cached or [])


def _baseline_dates_uncached(as_of: str, n: int) -> list[str]:
    raw = trade_calendar.trade_dates_ending_at(as_of, n + 2)
    return [d for d in raw if d < as_of][-n:]


def _zt_minus_dt(zt: Any, dt: Any) -> Optional[float]:
    a, b = _f(zt), _f(dt)
    if a is None or b is None:
        return None
    return a - b


def _from_emotion_dict(emo: dict[str, Any]) -> dict[str, Optional[float]]:
    if not emo:
        return {k: None for k in ("max_boards", "promotion_rate", "break_rate", "zt_minus_dt")}
    return {
        "max_boards": _f(emo.get("max_boards")),
        "promotion_rate": _f(emo.get("promotion_rate")),
        "break_rate": _f(emo.get("break_rate")),
        "zt_minus_dt": _zt_minus_dt(emo.get("zt_count"), emo.get("dt_count")),
    }


def _from_pools(date: str) -> dict[str, Optional[float]]:
    """无打板情绪归档时，用定稿三池按同一口径现算。失败则各层 None。"""
    from . import settled_archive as sa
    from . import live_emotion as le

    p = sa.limit_pools(date)
    if not p or not p.get("zt"):
        return _from_emotion_dict({})
    prev = trade_calendar.prev_trade_date(date)
    prev_p = sa.limit_pools(prev) if prev else None

    def _em(rows: Optional[list]) -> Optional[list[dict]]:
        if rows is None:
            return None
        return [{"c": r.get("code"), "lbc": r.get("boards") or 1} for r in rows]

    metrics = le._metrics_from_pools(
        _em(p.get("zt")) or [],
        _em(p.get("zb")),
        _em(p.get("dt")),
        _em(prev_p.get("zt")) if prev_p else None,
    )
    return _from_emotion_dict(metrics)


def _day_board_emotion(date: str, live_snap: Optional[dict] = None) -> dict[str, Optional[float]]:
    if live_snap and live_snap.get("available") and live_snap.get("date") == date:
        return _from_emotion_dict(live_snap)
    from . import live_emotion as le

    archived = le._load_archive(date)
    if archived and any(k in archived for k in le._ARCHIVE_KEYS):
        return _from_emotion_dict(archived)
    return _from_pools(date)


def _day_money_loss(date: str) -> dict[str, Optional[float]]:
    from . import emotion_metrics as em
    from . import market_facts as mf

    money = em.money_effect(date)
    loss = mf.loss_effect(date)
    return {
        "money_avg": _f(money.get("avg")) if money.get("available") else None,
        "deep_loss_5_rate": (
            _f(loss.get("deep_loss_5_rate")) if loss.get("available") else None
        ),
    }


def day_readings(date: str, live_snap: Optional[dict] = None) -> dict[str, Optional[float]]:
    """一场次六层原值。已定稿且落盘完整则只读盘，不再打上游。"""
    live_hit = bool(
        live_snap and live_snap.get("available") and live_snap.get("date") == date
    )
    if not live_hit:
        now = time.monotonic()
        with _snap_lock:
            mem = _day_mem.get(date)
            if mem and now - mem[0] < mem[2]:
                return dict(mem[1])
        arch = _load_day(date)
        if arch.get("settled") and _day_complete(arch):
            out = _layers_from_arch(arch)
            _remember_day(date, out, _SETTLED_TTL)
            return out

    out = {k: None for k in LAYER_KEYS}
    out.update(_day_board_emotion(date, live_snap if live_hit else None))
    out.update(_day_money_loss(date))

    settled = _date_is_settled(date)
    ttl = _LIVE_TTL if live_hit or not settled else _SETTLED_TTL
    if any(v is not None for v in out.values()) and trade_calendar.should_write_daily_cache(date):
        payload: dict[str, Any] = {k: out.get(k) for k in LAYER_KEYS}
        payload["date"] = date
        if settled:
            payload["settled"] = True
        _save_day(date, payload)
        if settled:
            ttl = _SETTLED_TTL
    _remember_day(date, out, ttl)
    return out


def _gather_now(as_of: str) -> dict[str, Any]:
    calendar_today = _today()
    is_live = as_of == calendar_today
    live_snap: Optional[dict] = None
    if is_live:
        from . import live_emotion as le
        live_snap = le.snapshot(as_of)
        phase = live_snap.get("phase") if live_snap else None
        current = day_readings(as_of, live_snap)
    else:
        current = day_readings(as_of)
        phase = "已收盘" if _date_is_settled(as_of) else "非交易日"

    dates = baseline_dates(as_of)
    hist_by_day = {d: day_readings(d) for d in dates}
    window: dict[str, list[Optional[float]]] = {
        k: [hist_by_day[d].get(k) for d in dates] for k in LAYER_KEYS
    }
    return {
        "current": current,
        "window": window,
        "dates": dates,
        "phase": phase,
        "is_live": bool(is_live),
    }


def _packed_for(as_of: str) -> dict[str, Any]:
    """一场次的当场读数 + 对照窗。锁外取数；同场次并发只跑一次。"""
    now = time.monotonic()
    with _snap_lock:
        hit = _gather_cache.get(as_of)
        if hit and now - hit[0] < hit[2]:
            return hit[1]
        waiter = _inflight.get(as_of)
        leader = waiter is None
        if leader:
            waiter = threading.Event()
            _inflight[as_of] = waiter
    if not leader:
        waiter.wait(timeout=_INFLIGHT_WAIT)
        with _snap_lock:
            hit = _gather_cache.get(as_of)
        if hit:
            return hit[1]
        return _gather_now(as_of)

    try:
        packed = _gather_now(as_of)
        ttl = _LIVE_TTL if packed.get("is_live") else _SETTLED_TTL
        with _snap_lock:
            _gather_cache[as_of] = (time.monotonic(), packed, ttl)
        return packed
    finally:
        waiter.set()
        with _snap_lock:
            if _inflight.get(as_of) is waiter:
                _inflight.pop(as_of, None)


def snapshot(
    as_of: str | None = None,
    *,
    baselines: Optional[dict[str, Any]] = None,
    weights: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """一场次的打板情绪共振：默认分必有；传入基线/权重时另给试算。"""
    calendar_today = _today()
    if as_of is None:
        as_of, _prev, _is_live = _cached(
            f"asof:{calendar_today}", _CAL_TTL,
            lambda: trade_calendar.resolve_as_of(calendar_today),
        )
    packed = _packed_for(as_of)
    current = packed["current"]
    window = packed["window"]
    dates = packed["dates"]

    default = score_board_emotion(current, window, dates)
    trial = None
    if baselines or weights:
        trial = score_board_emotion(
            current, window, dates,
            weights=weights, baselines=baselines, trial=True,
        )

    return {
        "available": True,
        "date": as_of,
        "is_live": bool(packed.get("is_live")),
        "phase": packed.get("phase"),
        "window_dates": dates,
        "note": "东财四池混算 10cm / 20cm / 北交所 / ST，家数同向不是同一制度内的同向。",
        "default": default,
        "trial": trial,
    }
