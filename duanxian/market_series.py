"""市场日序列缓存 —— 两融、上证涨跌幅等（供 S 分位与宽度背离）。

优先 AKTools HTTP；不可用时回退本地 akshare。
落盘：`~/.duanxian-agents/cache/market_series/`
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from . import aktools_client as akc
from .util import atomic_write_json, china_now

_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/market_series")
_MARGIN_PATH = os.path.join(_CACHE_DIR, "margin_sse.json")
_INDEX_PATH = os.path.join(_CACHE_DIR, "sh000001.json")
_AMOUNT_PATH = os.path.join(_CACHE_DIR, "market_amount.json")
_BREADTH_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/breadth")
_SHORT_BOARD_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/short_board")
_AMOUNT_MA_WINDOW = 20
_AMOUNT_PCT_LOOKBACK = 220
_SCHEMA = 1
_LOCK = threading.Lock()
_BG_LOCK = threading.Lock()
_BG_RUNNING = False


def _ymd_compact(date: str) -> str:
    return str(date).replace("-", "")


def _ymd_dash(raw: str) -> Optional[str]:
    s = str(raw or "").strip()
    if not s:
        return None
    s = s.replace("T", " ").split(" ")[0].replace("/", "-")
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _load_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"schema": _SCHEMA, "rows": [], "updated_at": None}
    try:
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        if isinstance(env, dict) and isinstance(env.get("rows"), list):
            return env
    except Exception:  # noqa: BLE001
        pass
    return {"schema": _SCHEMA, "rows": [], "updated_at": None}


def _save_json(path: str, rows: list[dict]) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    env = {
        "schema": _SCHEMA,
        "rows": rows,
        "updated_at": china_now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "aktools" if akc.available() else "akshare",
    }
    atomic_write_json(path, env)
    return env


def _merge_by_date(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """按 date 合并行，incoming 覆盖同日期。"""
    by: dict[str, dict] = {str(r["date"]): r for r in existing if r.get("date")}
    for row in incoming:
        d = row.get("date")
        if d:
            by[str(d)] = row
    return sorted(by.values(), key=lambda r: str(r["date"]))


def _apply_margin_chg(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, row in enumerate(rows):
        item = dict(row)
        if i == 0 or item.get("margin_balance") is None or rows[i - 1].get("margin_balance") in (None, 0):
            item["margin_chg"] = None
        else:
            prev = float(rows[i - 1]["margin_balance"])
            cur = float(item["margin_balance"])
            item["margin_chg"] = round((cur - prev) / prev * 100.0, 4)
        out.append(item)
    return out


def _apply_index_pct(rows: list[dict]) -> list[dict]:
    tmp = sorted(rows, key=lambda r: str(r["date"]))
    out: list[dict] = []
    for i, row in enumerate(tmp):
        pct = None
        if i > 0 and tmp[i - 1].get("close"):
            pct = round((float(row["close"]) / float(tmp[i - 1]["close"]) - 1.0) * 100.0, 4)
        out.append({"date": row["date"], "close": row["close"], "pct": pct})
    return out


def _margin_refresh_meta(rows: list[dict], env: dict, *, mode: str, added: int = 0) -> dict[str, Any]:
    return {
        "ok": True,
        "days": len(rows),
        "first": rows[0]["date"] if rows else None,
        "last": rows[-1]["date"] if rows else None,
        "updated_at": env.get("updated_at"),
        "source": env.get("source"),
        "mode": mode,
        "added": added,
    }


def _index_refresh_meta(rows: list[dict], env: dict, *, mode: str, added: int = 0) -> dict[str, Any]:
    return {
        "ok": True,
        "days": len(rows),
        "first": rows[0]["date"] if rows else None,
        "last": rows[-1]["date"] if rows else None,
        "updated_at": env.get("updated_at"),
        "source": env.get("source"),
        "mode": mode,
        "added": added,
    }


# ------------------------------------------------------------------ 两融
def _fetch_margin_rows(*, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
    start_c = _ymd_compact(start) if start else None
    end_c = _ymd_compact(end) if end else None
    raw: Any = None
    if akc.available():
        try:
            raw = akc.public(
                "stock_margin_sse",
                start_date=start_c,
                end_date=end_c,
            )
        except Exception:  # noqa: BLE001
            raw = None
    if raw is None:
        import akshare as ak

        kw = {}
        if start_c:
            kw["start_date"] = start_c
        if end_c:
            kw["end_date"] = end_c
        df = ak.stock_margin_sse(**kw) if kw else ak.stock_margin_sse()
        raw = df.to_dict(orient="records") if df is not None and len(df) else []

    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        d = _ymd_dash(str(row.get("信用交易日期") or row.get("date") or ""))
        if not d:
            continue
        bal = row.get("融资余额")
        buy = row.get("融资买入额")
        try:
            bal_f = float(bal) if bal is not None else None
        except (TypeError, ValueError):
            bal_f = None
        try:
            buy_f = float(buy) if buy is not None else None
        except (TypeError, ValueError):
            buy_f = None
        out.append({"date": d, "margin_balance": bal_f, "margin_buy": buy_f})
    out.sort(key=lambda r: r["date"])
    return out


def refresh_margin(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    incremental: bool = True,
    force_full: bool = False,
) -> dict[str, Any]:
    """刷新两融。默认在已有缓存时只拉 last→target 增量并合并。"""
    from . import trade_calendar as tc

    with _LOCK:
        existing = list(_load_json(_MARGIN_PATH).get("rows") or [])
        target = end or _target_trade_date()

        if force_full or not existing or not incremental or start is not None:
            rows = _apply_margin_chg(_fetch_margin_rows(start=start, end=end or target))
            if not rows:
                raise RuntimeError("两融序列为空")
            env = _save_json(_MARGIN_PATH, rows)
            return _margin_refresh_meta(rows, env, mode="full", added=len(rows))

        last = str(existing[-1].get("date") or "")
        if target and last >= target:
            env = _load_json(_MARGIN_PATH)
            return _margin_refresh_meta(existing, env, mode="skip", added=0)

        fetch_start = tc.next_trade_date(last) or last
        if not target or fetch_start > target:
            env = _load_json(_MARGIN_PATH)
            return _margin_refresh_meta(existing, env, mode="skip", added=0)

        delta = _fetch_margin_rows(start=fetch_start, end=target)
        if not delta:
            env = _load_json(_MARGIN_PATH)
            return _margin_refresh_meta(existing, env, mode="skip", added=0)

        merged = _apply_margin_chg(_merge_by_date(existing, delta))
        env = _save_json(_MARGIN_PATH, merged)
        return _margin_refresh_meta(
            merged,
            env,
            mode="incremental",
            added=len(merged) - len(existing),
        )


def margin_for(date: str) -> Optional[dict]:
    rows = _load_json(_MARGIN_PATH).get("rows") or []
    for r in rows:
        if r.get("date") == date:
            return r
    return None


def margin_map() -> dict[str, dict]:
    return {r["date"]: r for r in (_load_json(_MARGIN_PATH).get("rows") or []) if r.get("date")}


# ------------------------------------------------------------------ 上证指数
def _parse_index_raw(raw: list) -> list[dict]:
    tmp: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        d = _ymd_dash(
            str(row.get("date") or row.get("日期") or row.get("time") or "")
        )
        if not d:
            continue
        close_raw = row.get("close")
        if close_raw is None:
            close_raw = row.get("收盘")
        try:
            close = float(close_raw) if close_raw is not None else None
        except (TypeError, ValueError):
            close = None
        if close is None:
            continue
        tmp.append({"date": d, "close": close})
    tmp.sort(key=lambda r: r["date"])
    return tmp


def _fetch_index_rows(*, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
    start_c = _ymd_compact(start) if start else None
    end_c = _ymd_compact(end) if end else None
    ranged = bool(start_c or end_c)
    raw: Any = None

    if ranged:
        if akc.available():
            try:
                raw = akc.public(
                    "index_zh_a_hist",
                    symbol="000001",
                    period="daily",
                    start_date=start_c or "19700101",
                    end_date=end_c or "22220101",
                )
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None:
            import akshare as ak

            df = ak.index_zh_a_hist(
                symbol="000001",
                period="daily",
                start_date=start_c or "19700101",
                end_date=end_c or "22220101",
            )
            raw = df.to_dict(orient="records") if df is not None and len(df) else []
    else:
        if akc.available():
            try:
                raw = akc.public("stock_zh_index_daily", symbol="sh000001")
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None:
            import akshare as ak

            df = ak.stock_zh_index_daily(symbol="sh000001")
            raw = df.to_dict(orient="records") if df is not None and len(df) else []

    if not isinstance(raw, list):
        return []
    return _apply_index_pct(_parse_index_raw(raw))


def refresh_index(*, incremental: bool = True, force_full: bool = False) -> dict[str, Any]:
    """刷新上证日线。默认在已有缓存时只拉 last→target 增量并合并。"""
    from . import trade_calendar as tc

    with _LOCK:
        existing = list(_load_json(_INDEX_PATH).get("rows") or [])
        target = _target_trade_date()

        if force_full or not existing or not incremental:
            rows = _fetch_index_rows()
            if not rows:
                raise RuntimeError("上证指数日线为空")
            env = _save_json(_INDEX_PATH, rows)
            return _index_refresh_meta(rows, env, mode="full", added=len(rows))

        last = str(existing[-1].get("date") or "")
        if target and last >= target:
            env = _load_json(_INDEX_PATH)
            return _index_refresh_meta(existing, env, mode="skip", added=0)

        fetch_start = tc.next_trade_date(last) or last
        if not target or fetch_start > target:
            env = _load_json(_INDEX_PATH)
            return _index_refresh_meta(existing, env, mode="skip", added=0)

        delta = _fetch_index_rows(start=fetch_start, end=target)
        if not delta:
            env = _load_json(_INDEX_PATH)
            return _index_refresh_meta(existing, env, mode="skip", added=0)

        merged = _apply_index_pct(
            _merge_by_date(
                [{"date": r["date"], "close": r["close"]} for r in existing],
                [{"date": r["date"], "close": r["close"]} for r in delta],
            )
        )
        env = _save_json(_INDEX_PATH, merged)
        return _index_refresh_meta(
            merged,
            env,
            mode="incremental",
            added=len(merged) - len(existing),
        )


def index_pct_for(date: str) -> Optional[float]:
    for r in _load_json(_INDEX_PATH).get("rows") or []:
        if r.get("date") == date and r.get("pct") is not None:
            return float(r["pct"])
    return None


# ------------------------------------------------------------------ 两市成交额（相对 20 日均 / 分位）
def _parse_sse_amount_yi(records: list) -> Optional[float]:
    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("单日情况") or "").strip() != "成交金额":
            continue
        try:
            v = float(row.get("股票"))
        except (TypeError, ValueError):
            return None
        return round(v, 2) if v >= 0 else None
    return None


def _parse_szse_amount_yi(records: list) -> Optional[float]:
    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("证券类别") or "").strip() != "股票":
            continue
        try:
            v = float(row.get("成交金额"))
        except (TypeError, ValueError):
            return None
        return round(v / 1e8, 2) if v >= 0 else None
    return None


def _fetch_amount_one(date: str) -> Optional[float]:
    """上交所 + 深交所股票成交额合计（亿元）。"""
    d = _ymd_compact(date)
    sse_raw: Any = None
    sz_raw: Any = None
    if akc.available():
        try:
            sse_raw = akc.public("stock_sse_deal_daily", date=d)
        except Exception:  # noqa: BLE001
            sse_raw = None
        try:
            sz_raw = akc.public("stock_szse_summary", date=d)
        except Exception:  # noqa: BLE001
            sz_raw = None
    if sse_raw is None or sz_raw is None:
        import akshare as ak

        if sse_raw is None:
            try:
                df = ak.stock_sse_deal_daily(date=d)
                sse_raw = df.to_dict(orient="records") if df is not None and len(df) else []
            except Exception:  # noqa: BLE001
                sse_raw = None
        if sz_raw is None:
            try:
                df = ak.stock_szse_summary(date=d)
                sz_raw = df.to_dict(orient="records") if df is not None and len(df) else []
            except Exception:  # noqa: BLE001
                sz_raw = None
    if not isinstance(sse_raw, list) or not isinstance(sz_raw, list):
        return None
    sse = _parse_sse_amount_yi(sse_raw)
    sz = _parse_szse_amount_yi(sz_raw)
    if sse is None or sz is None:
        return None
    return round(sse + sz, 2)


def _seed_amount_from_caches() -> dict[str, float]:
    """从 breadth / short_board 既有按日落盘里捞成交额，减少回拉。"""
    out: dict[str, float] = {}
    if os.path.isdir(_BREADTH_CACHE_DIR):
        for name in os.listdir(_BREADTH_CACHE_DIR):
            if not name.endswith(".json"):
                continue
            date = name[:-5]
            if len(date) != 10:
                continue
            try:
                with open(os.path.join(_BREADTH_CACHE_DIR, name), encoding="utf-8") as fh:
                    env = json.load(fh)
                data = env.get("data") if isinstance(env, dict) else None
                if isinstance(data, dict) and data.get("available"):
                    v = data.get("amount_yi")
                    if isinstance(v, (int, float)) and v >= 0:
                        out[date] = round(float(v), 2)
            except Exception:  # noqa: BLE001
                pass
    if os.path.isdir(_SHORT_BOARD_CACHE_DIR):
        for name in os.listdir(_SHORT_BOARD_CACHE_DIR):
            if not name.endswith(".json"):
                continue
            date = name[:-5]
            if len(date) != 10:
                continue
            try:
                with open(os.path.join(_SHORT_BOARD_CACHE_DIR, name), encoding="utf-8") as fh:
                    env = json.load(fh)
                if isinstance(env, dict):
                    v = env.get("v_ca")
                    if isinstance(v, (int, float)) and v > 0:
                        out.setdefault(date, round(float(v) / 1e8, 2))
            except Exception:  # noqa: BLE001
                pass
    return out


def _amount_rows_sorted() -> list[dict]:
    return list(_load_json(_AMOUNT_PATH).get("rows") or [])


def amount_for(date: str) -> Optional[dict]:
    for r in _amount_rows_sorted():
        if r.get("date") == date:
            return r
    return None


def amount_metrics_for(date: str) -> Optional[dict[str, Any]]:
    """某日成交额 + 相对 20 日均 + 近窗分位。"""
    rows = _amount_rows_sorted()
    if not rows:
        return None
    hist: list[float] = []
    hit: Optional[dict] = None
    for row in rows:
        d = row.get("date")
        v = row.get("amount_yi")
        if d == date:
            hit = row
            break
        if d and v is not None:
            hist.append(float(v))
    if not hit or hit.get("amount_yi") is None:
        return None
    cur = float(hit["amount_yi"])
    all_vals = hist + [cur]
    ma_vals = hist[-_AMOUNT_MA_WINDOW:]
    ma20 = round(sum(ma_vals) / len(ma_vals), 2) if len(ma_vals) >= _AMOUNT_MA_WINDOW else None
    ratio = round(cur / ma20, 4) if ma20 and ma20 > 0 else None
    window = (hist + [cur])[-_AMOUNT_PCT_LOOKBACK:]
    pctile = None
    if len(window) >= 5:
        less = sum(1 for x in window if x < cur)
        equal = sum(1 for x in window if x == cur)
        pctile = round((less + 0.5 * equal) / len(window) * 100.0, 2)
    return {
        "date": date,
        "amount_yi": cur,
        "ma20_yi": ma20,
        "amount_vs_ma20": ratio,
        "amount_pctile": pctile,
    }


def amount_metrics_map() -> dict[str, dict]:
    rows = _amount_rows_sorted()
    out: dict[str, dict] = {}
    hist: list[float] = []
    for row in rows:
        d = row.get("date")
        if not d or row.get("amount_yi") is None:
            continue
        cur = float(row["amount_yi"])
        ma_vals = hist[-_AMOUNT_MA_WINDOW:]
        ma20 = round(sum(ma_vals) / len(ma_vals), 2) if len(ma_vals) >= _AMOUNT_MA_WINDOW else None
        ratio = round(cur / ma20, 4) if ma20 and ma20 > 0 else None
        window = (hist + [cur])[-_AMOUNT_PCT_LOOKBACK:]
        pctile = None
        if len(window) >= 5:
            less = sum(1 for x in window if x < cur)
            equal = sum(1 for x in window if x == cur)
            pctile = round((less + 0.5 * equal) / len(window) * 100.0, 2)
        out[str(d)] = {
            "amount_yi": cur,
            "ma20_yi": ma20,
            "amount_vs_ma20": ratio,
            "amount_pctile": pctile,
        }
        hist.append(cur)
    return out


def _missing_amount_dates(target: str, existing: dict[str, float]) -> list[str]:
    from . import trade_calendar as tc

    if not existing:
        dates = tc.trade_dates_ending_at(target, _AMOUNT_PCT_LOOKBACK) or []
        return [d for d in dates if d not in existing]
    last = max(existing)
    if last >= target:
        return []
    out: list[str] = []
    cur = tc.next_trade_date(last)
    guard = 0
    while cur and cur <= target and guard < _AMOUNT_PCT_LOOKBACK + 5:
        if cur not in existing:
            out.append(cur)
        cur = tc.next_trade_date(cur)
        guard += 1
    return out


def refresh_amount(
    *,
    incremental: bool = True,
    force_full: bool = False,
    max_fetch: Optional[int] = 30,
) -> dict[str, Any]:
    """刷新两市股票成交额序列（亿元）。默认增量，每轮最多新拉 max_fetch 天。"""
    import time

    with _LOCK:
        target = _target_trade_date()
        if not target:
            raise RuntimeError("无法确定最近交易日")

        existing: dict[str, float] = {}
        if not force_full:
            for row in _amount_rows_sorted():
                if row.get("date") and row.get("amount_yi") is not None:
                    existing[str(row["date"])] = float(row["amount_yi"])
            existing.update(_seed_amount_from_caches())

        if force_full:
            existing = {}

        missing = _missing_amount_dates(target, existing)
        if not incremental and not force_full:
            missing = missing or _missing_amount_dates(target, {})

        fetched = 0
        for date in missing:
            if max_fetch is not None and fetched >= max_fetch:
                break
            val = _fetch_amount_one(date)
            if val is not None:
                existing[date] = val
                fetched += 1
            time.sleep(0.15)

        if not existing:
            raise RuntimeError("成交额序列为空")

        rows = [{"date": d, "amount_yi": existing[d]} for d in sorted(existing)]
        env = _save_json(_AMOUNT_PATH, rows)
        mode = "full" if force_full or not incremental else ("incremental" if fetched else "skip")
        return {
            "ok": True,
            "days": len(rows),
            "first": rows[0]["date"],
            "last": rows[-1]["date"],
            "updated_at": env.get("updated_at"),
            "source": env.get("source"),
            "mode": mode,
            "added": fetched,
            "pending": max(0, len(missing) - fetched),
        }


def amount_needs_refresh() -> Optional[str]:
    target = _target_trade_date()
    rows = _amount_rows_sorted()
    if not rows:
        return "成交额缓存为空"
    if not target:
        return None
    last = str(rows[-1].get("date") or "")
    if last < target:
        return f"成交额止于 {last}，落后 {target}"
    return None


# ------------------------------------------------------------------ 涨停三池摘要（给分位 enrich）
def zt_summary_via_aktools(date: str) -> Optional[dict[str, Any]]:
    """用 AKTools 按日取涨停/炸板池，算出 highest + broken_rate。失败返回 None。"""
    if not akc.available():
        return None
    d = _ymd_compact(date)
    try:
        zt = akc.public("stock_zt_pool_em", date=d)
        zb = akc.public("stock_zt_pool_zbgc_em", date=d)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(zt, list) or not zt:
        return None
    if not isinstance(zb, list):
        zb = []
    highest = 0
    for row in zt:
        if not isinstance(row, dict):
            continue
        try:
            b = int(row.get("连板数") or 0)
        except (TypeError, ValueError):
            b = 0
        if b > highest:
            highest = b
    n_zt, n_zb = len(zt), len(zb)
    br = round(n_zb / (n_zt + n_zb), 3) if (n_zt + n_zb) else None
    return {
        "highest": highest or None,
        "broken_rate": br,
        "limit_up": n_zt,
        "broken": n_zb,
        "em_ok": True,
        "source": "aktools",
    }


def refresh_all(
    *,
    margin_start: Optional[str] = None,
    force_full: bool = False,
    amount_max_fetch: Optional[int] = 30,
) -> dict[str, Any]:
    """刷新两融 + 上证日线 + 成交额（默认增量）。"""
    out: dict[str, Any] = {"aktools": akc.status()}
    try:
        out["margin"] = refresh_margin(
            start=margin_start,
            incremental=margin_start is None,
            force_full=force_full or margin_start is not None,
        )
    except Exception as exc:  # noqa: BLE001
        out["margin"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        out["index"] = refresh_index(incremental=not force_full, force_full=force_full)
    except Exception as exc:  # noqa: BLE001
        out["index"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        out["amount"] = refresh_amount(
            incremental=not force_full,
            force_full=force_full,
            max_fetch=None if force_full else amount_max_fetch,
        )
    except Exception as exc:  # noqa: BLE001
        out["amount"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


def _target_trade_date() -> Optional[str]:
    """最近一个已收盘交易日。"""
    from . import trade_calendar as tc

    dates = tc.last_trade_dates(1)
    return dates[-1] if dates else None


def needs_refresh() -> Optional[str]:
    """缓存落后或为空时返回原因；已足够新则 None。"""
    target = _target_trade_date()
    mr = (_load_json(_MARGIN_PATH).get("rows") or [])
    ir = (_load_json(_INDEX_PATH).get("rows") or [])
    if not mr:
        return "两融缓存为空"
    if not ir:
        return "上证日线缓存为空"
    if not target:
        return None
    m_last = str(mr[-1].get("date") or "")
    i_last = str(ir[-1].get("date") or "")
    if m_last < target:
        return f"两融止于 {m_last}，落后 {target}"
    if i_last < target:
        return f"上证止于 {i_last}，落后 {target}"
    amt = amount_needs_refresh()
    if amt:
        return amt
    return None


def ensure_fresh(*, force: bool = False) -> dict[str, Any]:
    """缺数据或落后最近交易日时自动刷新；已最新则跳过。"""
    reason = needs_refresh()
    if not force and reason is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": None,
            "status": series_status(),
        }
    out = refresh_all(force_full=force)
    out["skipped"] = False
    out["reason"] = reason or "force"
    out["ok"] = bool(
        (out.get("margin") or {}).get("ok") or (out.get("index") or {}).get("ok")
    )
    out["status"] = series_status()
    return out


def ensure_fresh_background() -> None:
    """后台补全两融/指数，不阻塞主服务启动。"""
    global _BG_RUNNING
    with _BG_LOCK:
        if _BG_RUNNING:
            return
        _BG_RUNNING = True

    def _job() -> None:
        global _BG_RUNNING
        try:
            from . import aktools_service as aks

            aks.ensure_started(wait_s=15.0)
            result = ensure_fresh()
            if result.get("skipped"):
                print("✓ 市场序列缓存已是最新")
                return
            m = result.get("margin") or {}
            i = result.get("index") or {}
            if m.get("ok") or i.get("ok"):
                print(
                    f"✓ 市场序列已刷新：两融 {m.get('days', '?')} 日 · "
                    f"上证 {i.get('days', '?')} 日"
                )
            else:
                err = m.get("error") or i.get("error") or "未知错误"
                print(f"⚠ 市场序列刷新失败：{err}")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ 市场序列后台刷新失败：{type(exc).__name__}: {exc}")
        finally:
            with _BG_LOCK:
                _BG_RUNNING = False

    threading.Thread(target=_job, name="market-series-refresh", daemon=True).start()


def series_status() -> dict[str, Any]:
    from . import aktools_service as aks

    m = _load_json(_MARGIN_PATH)
    idx = _load_json(_INDEX_PATH)
    amt = _load_json(_AMOUNT_PATH)
    mr = m.get("rows") or []
    ir = idx.get("rows") or []
    ar = amt.get("rows") or []
    return {
        "aktools": aks.runtime_status(),
        "margin": {
            "days": len(mr),
            "first": mr[0]["date"] if mr else None,
            "last": mr[-1]["date"] if mr else None,
            "updated_at": m.get("updated_at"),
            "path": _MARGIN_PATH,
        },
        "index": {
            "days": len(ir),
            "first": ir[0]["date"] if ir else None,
            "last": ir[-1]["date"] if ir else None,
            "updated_at": idx.get("updated_at"),
            "path": _INDEX_PATH,
        },
        "amount": {
            "days": len(ar),
            "first": ar[0]["date"] if ar else None,
            "last": ar[-1]["date"] if ar else None,
            "updated_at": amt.get("updated_at"),
            "path": _AMOUNT_PATH,
            "needs_refresh": amount_needs_refresh(),
            "ma_window": _AMOUNT_MA_WINDOW,
            "ma_ready": len(ar) >= _AMOUNT_MA_WINDOW,
        },
    }
