"""短线风格轮动：定稿存档 + 相邻已定稿场次派生。

只比较相邻已定稿场次；未定稿随盘不得当本场或上场。缺上场不拿更早场次顶上，
缺样本日不插值。不打网络（日历与磁盘除外）。
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from typing import Any, Optional

from . import paths as _paths
from . import trade_calendar
from .util import atomic_write_json

Z_N = 10
CLOSE_N = 20
SPEARMAN_MIN_N = 2
SIGMA_EPS = 1e-12

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CACHE_DIR = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "style_indices")


def empty_rotation(*, live_deferred: bool = False) -> dict:
    return {
        "status": "absent",
        "this": None,
        "against": None,
        "live_deferred": live_deferred,
        "hotspot_enter": [],
        "hotspot_leave": [],
        "spearman": {"value": None, "n": 0, "status": "不足"},
        "z_n": Z_N,
        "close_n": CLOSE_N,
    }


def _archive_path(date: str) -> str:
    if not _DATE_RE.match(date):
        raise ValueError(f"非法日期 {date!r}")
    return os.path.join(_CACHE_DIR, f"{date}.json")


def save_archive(date: str, quotes: dict[str, dict]) -> None:
    """同一场次定稿可覆盖写。锁外磁盘 IO。"""
    if not _CACHE_DIR or not quotes:
        return
    try:
        path = _archive_path(date)
    except ValueError:
        return
    payload = {"date": date, "quotes": quotes}
    atomic_write_json(path, payload)


def load_archive(date: Optional[str]) -> Optional[dict[str, dict]]:
    """返回 {key: quote}；缺档或坏档为 None（调用方当不足，不跳日）。"""
    if not date or not _CACHE_DIR:
        return None
    try:
        path = _archive_path(date)
    except ValueError:
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    quotes = data.get("quotes")
    if not isinstance(quotes, dict):
        return None
    return quotes


def rotation_pair(as_of: str, prev: Optional[str], settled: bool) -> tuple[Optional[str], Optional[str], bool]:
    """(本场定稿日, 上场定稿日, 是否因本场未定稿而改看最近两场已定稿)。"""
    if settled:
        return as_of, prev, False
    this_d = prev
    prev_d = trade_calendar.prev_trade_date(this_d) if this_d else None
    if prev_d and this_d and prev_d >= this_d:
        prev_d = None
    return this_d, prev_d, True


def _chain_prev(end: str, n: int) -> list[str]:
    """end 之前最多 n 个交易日（升序）。一次日历查询，不插值。"""
    if n <= 0:
        return []
    raw = trade_calendar.trade_dates_ending_at(end, n + 2)
    return [d for d in raw if d < end][-n:]


def _assemble(quotes: dict[str, dict]) -> dict:
    from .style_indices import assemble

    return assemble(quotes)


def _by_key(packed: dict) -> dict[str, dict]:
    from .style_indices import items_by_key

    return items_by_key(packed)


def _pct(item: Optional[dict]) -> Optional[float]:
    if not item or not item.get("available"):
        return None
    v = item.get("change_pct")
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def _price(item: Optional[dict]) -> Optional[float]:
    if not item:
        return None
    v = item.get("price")
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def hotspot_keys_of(packed: dict) -> list[str]:
    pref = packed.get("preference") or {}
    if pref.get("status") != "ok":
        return []
    return [h["key"] for h in (pref.get("hotspots") or [])]


def excess_ranks(packed: dict) -> Optional[dict[str, int]]:
    """候选集 1-based 超额位次。缺中证全指则 None（整场不报位次）。"""
    from .style_indices import rank_hotspot_candidates

    by_key = _by_key(packed)
    csi = _pct(by_key.get("csi_all"))
    if csi is None:
        return None
    ranked = rank_hotspot_candidates(by_key, csi)
    return {it["key"]: i + 1 for i, it in enumerate(ranked)}


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < SPEARMAN_MIN_N:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx < SIGMA_EPS or vy < SIGMA_EPS:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(vx * vy)


def spearman_of_ranks(
    this_ranks: Optional[dict[str, int]],
    prev_ranks: Optional[dict[str, int]],
) -> dict:
    if not this_ranks or not prev_ranks:
        return {"value": None, "n": 0, "status": "不足"}
    keys = [k for k in this_ranks if k in prev_ranks]
    n = len(keys)
    if n < SPEARMAN_MIN_N:
        return {"value": None, "n": n, "status": "不足"}
    xs = [float(this_ranks[k]) for k in keys]
    ys = [float(prev_ranks[k]) for k in keys]
    rho = _pearson(xs, ys)
    if rho is None:
        return {"value": None, "n": n, "status": "不足"}
    return {"value": round(rho, 4), "n": n, "status": "ok"}


def derive_rotation(
    this_packed: Optional[dict],
    prev_packed: Optional[dict],
    this_date: Optional[str],
    prev_date: Optional[str],
    *,
    live_deferred: bool,
) -> dict:
    """热点进入/离开 + Spearman。有对照日期但热点不能比 → partial。"""
    out = empty_rotation(live_deferred=live_deferred)
    if not this_date or not prev_date:
        return out
    if this_packed is None or prev_packed is None:
        return out

    out["this"] = {"date": this_date}
    out["against"] = {"date": prev_date}

    this_pref = (this_packed.get("preference") or {}).get("status")
    prev_pref = (prev_packed.get("preference") or {}).get("status")
    hotspots_ok = this_pref == "ok" and prev_pref == "ok"
    if hotspots_ok:
        this_h = set(hotspot_keys_of(this_packed))
        prev_h = set(hotspot_keys_of(prev_packed))
        from .style_indices import _ITEM_ORDER

        def ordered(keys: set[str]) -> list[str]:
            return sorted(keys, key=lambda k: _ITEM_ORDER.get(k, 10**6))

        out["hotspot_enter"] = ordered(this_h - prev_h)
        out["hotspot_leave"] = ordered(prev_h - this_h)
        out["status"] = "ok"
    else:
        out["status"] = "partial"

    this_ranks = excess_ranks(this_packed) if this_packed else None
    prev_ranks = excess_ranks(prev_packed) if prev_packed else None
    out["spearman"] = spearman_of_ranks(this_ranks, prev_ranks)
    return out


def close_extreme_keys() -> frozenset[str]:
    """编制稳定、点位可比：宽基、红利官方指数、国证2000、官方成长/价值、行业指数。换成分篮子不报。"""
    from .style_indices import ITEMS

    return frozenset(
        it.key for it in ITEMS
        if it.group in {"benchmark", "dividend", "sector"}
        or it.key in {"csi2000", "cni_growth", "cni_value", "csi_tech", "csi_cons"}
    )


def _quote_pct(quotes: Optional[dict[str, dict]], key: str) -> Optional[float]:
    if not quotes:
        return None
    row = quotes.get(key)
    if not isinstance(row, dict):
        return None
    v = row.get("change_pct")
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def _quote_price(quotes: Optional[dict[str, dict]], key: str) -> Optional[float]:
    if not quotes:
        return None
    row = quotes.get(key)
    if not isinstance(row, dict):
        return None
    v = row.get("price")
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return n


def _zscore(r_this: Optional[float], window: list[Optional[float]]) -> Optional[float]:
    if r_this is None:
        return None
    if len(window) != Z_N or any(v is None for v in window):
        return None
    vals = [float(v) for v in window if v is not None]
    if len(vals) != Z_N:
        return None
    mu = statistics.fmean(vals)
    sig = statistics.pstdev(vals)
    if sig < SIGMA_EPS:
        return 0.0
    return (r_this - mu) / sig


def _cum_excess(window_quotes: list[Optional[dict[str, dict]]], key: str) -> Optional[float]:
    if len(window_quotes) != Z_N or any(q is None for q in window_quotes):
        return None
    total = 0.0
    for q in window_quotes:
        r = _quote_pct(q, key)
        csi = _quote_pct(q, "csi_all")
        if r is None or csi is None:
            return None
        total += r - csi
    return total


def _close_label(prices: list[Optional[float]]) -> Optional[str]:
    """近 N 场收盘（含本场定稿）相对新高/新低。缺一则不足。"""
    if len(prices) != CLOSE_N or any(p is None for p in prices):
        return "不足"
    vals = [float(p) for p in prices if p is not None]
    if len(vals) != CLOSE_N:
        return "不足"
    current = vals[-1]
    hi, lo = max(vals), min(vals)
    if hi == lo:
        return "都不是"
    if current == hi:
        return "新高"
    if current == lo:
        return "新低"
    return "都不是"


def item_metrics(
    *,
    this_packed: Optional[dict],
    prev_packed: Optional[dict],
    as_of_settled: bool,
    z_quotes: list[Optional[dict[str, dict]]],
    close_quotes: list[Optional[dict[str, dict]]],
) -> dict[str, dict[str, Any]]:
    """按 key 给出涨幅差、超额位次变化、z、累计超额、收盘新高/新低。"""
    from .style_indices import HOTSPOT_GROUP_IDS, ITEMS

    eligible_close = close_extreme_keys()
    this_ranks = excess_ranks(this_packed) if this_packed else None
    prev_ranks = excess_ranks(prev_packed) if prev_packed else None
    this_items = _by_key(this_packed) if this_packed else {}
    prev_items = _by_key(prev_packed) if prev_packed else {}

    out: dict[str, dict[str, Any]] = {}
    for spec in ITEMS:
        key = spec.key
        this_pct = _pct(this_items.get(key))
        prev_pct = _pct(prev_items.get(key))
        if this_packed is None or prev_packed is None or prev_pct is None or this_pct is None:
            delta: Optional[float] = None
        else:
            delta = this_pct - prev_pct

        rank_delta: Optional[int] = None
        if this_ranks is not None and prev_ranks is not None:
            tr, pr = this_ranks.get(key), prev_ranks.get(key)
            if tr is not None and pr is not None:
                rank_delta = pr - tr

        z: Optional[float] = None
        cum: Optional[float] = None
        if as_of_settled:
            z = _zscore(this_pct, [_quote_pct(q, key) for q in z_quotes])
            if spec.group in HOTSPOT_GROUP_IDS and key != "csi_all":
                cum = _cum_excess(z_quotes, key)

        extreme: Optional[str] = None
        if key in eligible_close:
            extreme = _close_label([_quote_price(q, key) for q in close_quotes])

        out[key] = {
            "change_pct_delta": None if delta is None else round(delta, 6),
            "excess_rank_delta": rank_delta,
            "zscore": None if z is None else round(z, 4),
            "cum_excess": None if cum is None else round(cum, 6),
            "close_extreme": extreme,
        }
    return out


def _attach_item_fields(packed: dict, metrics: dict[str, dict[str, Any]]) -> None:
    for g in packed.get("groups") or []:
        for it in g.get("items") or []:
            m = metrics.get(it["key"]) or {
                "change_pct_delta": None,
                "excess_rank_delta": None,
                "zscore": None,
                "cum_excess": None,
                "close_extreme": None,
            }
            it["change_pct_delta"] = m["change_pct_delta"]
            it["excess_rank_delta"] = m["excess_rank_delta"]
            it["zscore"] = m["zscore"]
            it["cum_excess"] = m["cum_excess"]
            it["close_extreme"] = m["close_extreme"]


def apply_to_snapshot(packed: dict, *, as_of: str, prev: Optional[str], settled: bool) -> dict:
    """定稿则落盘；轮动只对相邻已定稿。未定稿本场的 z / 累计超额不报。"""
    from .style_indices import packed_quotes

    if settled and packed.get("available"):
        quotes = packed_quotes(packed)
        if quotes:
            save_archive(as_of, quotes)

    this_d, prev_d, deferred = rotation_pair(as_of, prev, settled)
    live_deferred = deferred

    this_q = load_archive(this_d)
    prev_q = load_archive(prev_d)
    this_packed = _assemble(this_q) if this_q is not None else None
    prev_packed = _assemble(prev_q) if prev_q is not None else None

    rot = derive_rotation(
        this_packed, prev_packed, this_d, prev_d, live_deferred=live_deferred,
    )

    z_dates = _chain_prev(this_d, Z_N) if this_d and settled else []
    close_dates = (
        (_chain_prev(this_d, CLOSE_N - 1) + [this_d]) if this_d else []
    )
    z_quotes: list[Optional[dict[str, dict]]] = (
        [load_archive(d) for d in z_dates] if len(z_dates) == Z_N else [None] * Z_N
    )
    close_quotes: list[Optional[dict[str, dict]]] = (
        [load_archive(d) for d in close_dates] if len(close_dates) == CLOSE_N else [None] * CLOSE_N
    )

    metrics = item_metrics(
        this_packed=this_packed,
        prev_packed=prev_packed,
        as_of_settled=settled,
        z_quotes=z_quotes,
        close_quotes=close_quotes,
    )
    _attach_item_fields(packed, metrics)
    packed["rotation"] = rot
    return packed
