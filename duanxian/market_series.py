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
_SCHEMA = 1
_LOCK = threading.Lock()


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
    # 日变化（相对昨）
    for i, row in enumerate(out):
        if i == 0 or row.get("margin_balance") is None or out[i - 1].get("margin_balance") in (None, 0):
            row["margin_chg"] = None
            continue
        prev = float(out[i - 1]["margin_balance"])
        cur = float(row["margin_balance"])
        row["margin_chg"] = round((cur - prev) / prev * 100.0, 4)  # 百分点
    return out


def refresh_margin(*, start: Optional[str] = None, end: Optional[str] = None) -> dict[str, Any]:
    with _LOCK:
        rows = _fetch_margin_rows(start=start, end=end)
        if not rows:
            raise RuntimeError("两融序列为空")
        env = _save_json(_MARGIN_PATH, rows)
        return {
            "ok": True,
            "days": len(rows),
            "first": rows[0]["date"],
            "last": rows[-1]["date"],
            "updated_at": env.get("updated_at"),
            "source": env.get("source"),
        }


def margin_for(date: str) -> Optional[dict]:
    rows = _load_json(_MARGIN_PATH).get("rows") or []
    for r in rows:
        if r.get("date") == date:
            return r
    return None


def margin_map() -> dict[str, dict]:
    return {r["date"]: r for r in (_load_json(_MARGIN_PATH).get("rows") or []) if r.get("date")}


# ------------------------------------------------------------------ 上证指数
def _fetch_index_rows() -> list[dict]:
    raw: Any = None
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
    tmp: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        d = _ymd_dash(str(row.get("date") or ""))
        if not d:
            continue
        try:
            close = float(row["close"]) if row.get("close") is not None else None
        except (TypeError, ValueError):
            close = None
        if close is None:
            continue
        tmp.append({"date": d, "close": close})
    tmp.sort(key=lambda r: r["date"])
    out: list[dict] = []
    for i, row in enumerate(tmp):
        pct = None
        if i > 0 and tmp[i - 1]["close"]:
            pct = round((row["close"] / tmp[i - 1]["close"] - 1.0) * 100.0, 4)
        out.append({"date": row["date"], "close": row["close"], "pct": pct})
    return out


def refresh_index() -> dict[str, Any]:
    with _LOCK:
        rows = _fetch_index_rows()
        if not rows:
            raise RuntimeError("上证指数日线为空")
        env = _save_json(_INDEX_PATH, rows)
        return {
            "ok": True,
            "days": len(rows),
            "first": rows[0]["date"],
            "last": rows[-1]["date"],
            "updated_at": env.get("updated_at"),
            "source": env.get("source"),
        }


def index_pct_for(date: str) -> Optional[float]:
    for r in _load_json(_INDEX_PATH).get("rows") or []:
        if r.get("date") == date and r.get("pct") is not None:
            return float(r["pct"])
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


def refresh_all(*, margin_start: Optional[str] = None) -> dict[str, Any]:
    """刷新两融 + 上证日线。"""
    out: dict[str, Any] = {"aktools": akc.status()}
    try:
        out["margin"] = refresh_margin(start=margin_start)
    except Exception as exc:  # noqa: BLE001
        out["margin"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        out["index"] = refresh_index()
    except Exception as exc:  # noqa: BLE001
        out["index"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


def series_status() -> dict[str, Any]:
    from . import aktools_service as aks

    m = _load_json(_MARGIN_PATH)
    idx = _load_json(_INDEX_PATH)
    mr = m.get("rows") or []
    ir = idx.get("rows") or []
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
    }
