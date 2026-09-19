"""账户风控闸：评估命中、落盘持仓快照、发出风控禁止买入。

纯计算不碰锁；sync_after_update 在账户/持仓更新后整份覆盖当日快照再评估。
"""

from __future__ import annotations

from typing import Any, Optional

from . import risk_guard_config as rgc
from .util import china_today

GATE_SINGLE = "single_holding_loss"
GATE_BOOK = "book_loss"
GATE_LOSING_DAYS = "losing_days"
GATE_UNION = "losing_holdings_union"
GATE_MAX_DD = "max_dd"

_GATE_LABEL = {
    GATE_SINGLE: "单只持仓亏损",
    GATE_BOOK: "总仓位亏损",
    GATE_LOSING_DAYS: "连亏天数",
    GATE_UNION: "亏损持仓累积",
    GATE_MAX_DD: "峰值回撤",
}


def session_date() -> str:
    """风控当日场次：交易日用日历今天，否则最近已收盘场次。"""
    from . import trade_calendar as tc

    today = china_today()
    if tc.is_trade_date(today):
        return today
    return tc.latest_session() or today


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def holding_pnl_amount(row: dict) -> Optional[float]:
    pnl = _f(row.get("pnl"))
    if pnl is not None:
        return pnl
    cost = _f(row.get("cost"))
    shares = _f(row.get("shares"))
    price = _f(row.get("price"))
    if cost is None or shares is None or shares <= 0:
        return None
    if price is not None:
        return price * shares - cost * shares
    pct = _f(row.get("pnl_pct"))
    if pct is None:
        return None
    return (pct / 100.0) * cost * shares


def holding_loss_ratio(row: dict) -> Optional[float]:
    """亏损为负比例。浮盈比例优先（百分数点），否则浮盈÷成本金额。"""
    pct = _f(row.get("pnl_pct"))
    if pct is not None:
        return pct / 100.0
    pnl = holding_pnl_amount(row)
    cost = _f(row.get("cost"))
    shares = _f(row.get("shares"))
    if pnl is None or cost is None or shares is None or cost * shares == 0:
        return None
    return pnl / (cost * shares)


def _snap_daily_loss_ratio(snap: dict) -> Optional[float]:
    pct = _f(snap.get("daily_pnl_pct"))
    if pct is not None:
        return pct / 100.0
    pnl = _f(snap.get("daily_pnl"))
    eq = _f(snap.get("equity"))
    if pnl is None or eq is None or eq == 0:
        return None
    return pnl / eq


def _snap_is_losing_day(snap: Optional[dict]) -> Optional[bool]:
    """None = 缺快照或无当日盈亏（打断连续）。"""
    if not isinstance(snap, dict):
        return None
    pnl = _f(snap.get("daily_pnl"))
    if pnl is not None:
        return pnl < 0
    pct = _f(snap.get("daily_pnl_pct"))
    if pct is not None:
        return pct < 0
    return None


def _hit(gate: str, level: str, message: str, extra: Optional[dict] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "gate": gate,
        "label": _GATE_LABEL[gate],
        "level": level,
        "message": message,
    }
    if extra:
        body.update(extra)
    return body


def evaluate(
    date: str,
    *,
    account: dict,
    holdings: list[dict],
    thresholds: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """根据账号快照、持仓快照与当前持仓评估全部闸。不写盘。"""
    cfg = dict(thresholds or rgc.resolved())
    snaps = account.get("snapshots") or {}
    hsnaps = account.get("holdings_snapshots") or {}
    hits: list[dict[str, Any]] = []

    # —— 单只持仓亏损（当前持仓）——
    single_soft = float(cfg["single_holding_loss_soft"])
    single_hard = float(cfg["single_holding_loss_hard"])
    single_soft_codes: list[str] = []
    single_hard_codes: list[str] = []
    for row in holdings or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        ratio = holding_loss_ratio(row)
        if ratio is None or ratio > -single_soft + 1e-12:
            continue
        if ratio <= -single_hard + 1e-12:
            single_hard_codes.append(code)
        else:
            single_soft_codes.append(code)
    if single_soft_codes or single_hard_codes:
        # 硬命中也算软提醒
        soft_codes = sorted(set(single_soft_codes + single_hard_codes))
        hits.append(_hit(
            GATE_SINGLE, "soft",
            f"单只持仓亏损软闸：{len(soft_codes)} 只浮盈比例 ≤ -{single_soft:.0%}",
            {"codes": soft_codes},
        ))
    if single_hard_codes:
        hits.append(_hit(
            GATE_SINGLE, "hard",
            f"单只持仓亏损硬闸：{len(single_hard_codes)} 只浮盈比例 ≤ -{single_hard:.0%}",
            {"codes": sorted(set(single_hard_codes))},
        ))

    # —— 总仓位亏损（当日账号快照）——
    book_soft = float(cfg["book_loss_soft"])
    book_hard = float(cfg["book_loss_hard"])
    today_snap = snaps.get(date) if isinstance(snaps, dict) else None
    book_ratio = _snap_daily_loss_ratio(today_snap) if isinstance(today_snap, dict) else None
    book_skipped = book_ratio is None
    if book_ratio is not None:
        if book_ratio <= -book_soft + 1e-12:
            hits.append(_hit(
                GATE_BOOK, "soft",
                f"总仓位亏损软闸：当日盈亏 {book_ratio:.2%} ≤ -{book_soft:.0%}",
                {"ratio": round(book_ratio, 6)},
            ))
        if book_ratio <= -book_hard + 1e-12:
            hits.append(_hit(
                GATE_BOOK, "hard",
                f"总仓位亏损硬闸：当日盈亏 {book_ratio:.2%} ≤ -{book_hard:.0%}",
                {"ratio": round(book_ratio, 6)},
            ))

    # —— 连亏天数 ——
    from . import trade_calendar as tc

    days_soft = int(round(float(cfg["losing_days_soft"])))
    days_hard = int(round(float(cfg["losing_days_hard"])))
    streak = 0
    cursor = date
    while cursor:
        flag = _snap_is_losing_day(snaps.get(cursor) if isinstance(snaps, dict) else None)
        if flag is not True:
            break
        streak += 1
        cursor = tc.prev_trade_date(cursor)
    if streak >= days_soft:
        hits.append(_hit(
            GATE_LOSING_DAYS, "soft",
            f"连亏天数软闸：连续 {streak} 日当日盈亏为负（≥ {days_soft}）",
            {"streak": streak},
        ))
    if streak >= days_hard:
        hits.append(_hit(
            GATE_LOSING_DAYS, "hard",
            f"连亏天数硬闸：连续 {streak} 日当日盈亏为负（≥ {days_hard}）",
            {"streak": streak},
        ))

    # —— 亏损持仓累积：近 N 个有持仓快照的交易日并集 ——
    union_soft = int(round(float(cfg["losing_holdings_union_soft"])))
    union_hard = int(round(float(cfg["losing_holdings_union_hard"])))
    hs_dates = sorted(
        d for d, body in (hsnaps or {}).items()
        if isinstance(body, dict) and isinstance(body.get("holdings"), list)
    )
    window_dates = hs_dates[-rgc.UNION_WINDOW_DAYS:]
    union_codes: set[str] = set()
    for d in window_dates:
        body = hsnaps.get(d) or {}
        for row in body.get("holdings") or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            amt = holding_pnl_amount(row)
            if amt is not None and amt < 0:
                union_codes.add(code)
    union_list = sorted(union_codes)
    if len(union_list) >= union_soft:
        hits.append(_hit(
            GATE_UNION, "soft",
            f"亏损持仓累积软闸：近 {len(window_dates)} 日并集 {len(union_list)} 只（≥ {union_soft}）",
            {"codes": union_list, "window_dates": window_dates},
        ))
    if len(union_list) >= union_hard:
        hits.append(_hit(
            GATE_UNION, "hard",
            f"亏损持仓累积硬闸：近 {len(window_dates)} 日并集 {len(union_list)} 只（≥ {union_hard}）",
            {"codes": union_list, "window_dates": window_dates},
        ))

    # —— 峰值回撤 ——
    dd_soft = float(cfg["max_dd_soft"])
    dd_hard = float(cfg["max_dd_hard"])
    equities: list[float] = []
    for body in (snaps or {}).values():
        if isinstance(body, dict):
            eq = _f(body.get("equity"))
            if eq is not None and eq > 0:
                equities.append(eq)
    cur_eq = _f(account.get("equity"))
    if cur_eq is not None and cur_eq > 0:
        equities.append(cur_eq)
    dd_ratio: Optional[float] = None
    if equities and cur_eq is not None and cur_eq > 0:
        peak = max(equities)
        if peak > 0:
            dd_ratio = (peak - cur_eq) / peak
            if dd_ratio >= dd_soft - 1e-12:
                hits.append(_hit(
                    GATE_MAX_DD, "soft",
                    f"峰值回撤软闸：{dd_ratio:.2%} ≥ {dd_soft:.0%}",
                    {"ratio": round(dd_ratio, 6), "peak": peak, "equity": cur_eq},
                ))
            if dd_ratio >= dd_hard - 1e-12:
                hits.append(_hit(
                    GATE_MAX_DD, "hard",
                    f"峰值回撤硬闸：{dd_ratio:.2%} ≥ {dd_hard:.0%}",
                    {"ratio": round(dd_ratio, 6), "peak": peak, "equity": cur_eq},
                ))

    hard_hits = [h for h in hits if h.get("level") == "hard"]
    global_no_buy = bool(hard_hits)
    reason = "；".join(h["message"] for h in hard_hits) if hard_hits else None
    meta: dict[str, Any] = {"source": "risk_guard", "level": 2 if global_no_buy else 0}
    union_hard_hit = next((h for h in hard_hits if h.get("gate") == GATE_UNION), None)
    if union_hard_hit:
        still_red = []
        for row in holdings or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if code and code in set(union_hard_hit.get("codes") or []):
                amt = holding_pnl_amount(row)
                if amt is not None and amt < 0:
                    still_red.append(code)
        meta["liquidate"] = True
        meta["codes"] = sorted(set(still_red))

    return {
        "date": date,
        "hits": hits,
        "global_no_buy": global_no_buy,
        "global_no_buy_reason": reason,
        "global_no_buy_meta": meta,
        "book_loss_skipped": book_skipped,
        "losing_day_streak": streak,
        "union_codes": union_list,
        "union_window_dates": window_dates,
        "drawdown": None if dd_ratio is None else round(dd_ratio, 6),
    }


def _live_holdings() -> list[dict]:
    try:
        import portfolio as pf

        data = pf.get_portfolio()
        rows = data.get("holdings") or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        return []


def freeze_holding_row(row: dict) -> dict[str, Any]:
    """快照只留评估需要的字段；浮盈在写入时冻结。"""
    code = str(row.get("code") or "").strip()
    pnl = holding_pnl_amount(row)
    ratio = holding_loss_ratio(row)
    pct = None if ratio is None else round(ratio * 100.0, 4)
    return {
        "code": code,
        "name": row.get("name"),
        "shares": _f(row.get("shares")),
        "cost": _f(row.get("cost")),
        "market_value": _f(row.get("market_value")),
        "pnl": None if pnl is None else round(pnl, 4),
        "pnl_pct": pct,
    }


def sync_after_update(
    *,
    date: str | None = None,
    holdings: Optional[list[dict]] = None,
    emit_hooks: bool = True,
) -> dict[str, Any]:
    """覆盖写当日持仓快照（及有权益时的账号快照），评估并可选派发钩子。锁外调用。"""
    from . import trade_store as ts

    day = date or session_date()
    rows = holdings if holdings is not None else _live_holdings()
    frozen = [freeze_holding_row(r) for r in rows if str(r.get("code") or "").strip()]
    ts.set_holdings_snapshot(day, frozen)
    account = ts.load_account()
    eq = _f(account.get("equity"))
    if eq is not None:
        mv = sum(float(r.get("market_value") or 0) for r in frozen)
        ts.snapshot_equity(day, mv)
        account = ts.load_account()
    result = evaluate(day, account=account, holdings=frozen)
    ts.set_last_risk_guard(result)
    if emit_hooks:
        try:
            from . import hooks

            hooks.RUNNER.emit_risk_guard(day, result)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 风控钩子派发失败（{day}）：{type(exc).__name__}: {exc}")
    return result
