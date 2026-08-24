"""当日风险姿态 —— 给定场次（+ 可选持仓/账户）给出档位、上限、理由、guard。

读数组装与定档同处；HTTP / 落盘只做 adapter。
`readings` 仍是定档输入，不把整份定稿日档案塞进预算。
"""

from __future__ import annotations

from typing import Any, Optional

from . import breadth, emotion_metrics as em, market_facts, trade_budget as tb
from . import trade_calendar


def _index_pct_for(date: str) -> Optional[float]:
    """仅当实时行情属于该已收盘日时取上证涨跌幅；历史日不强行冒充。"""
    ok, _ = trade_calendar.live_quotes_are_close_of(date)
    if not ok:
        return None
    try:
        from . import fetchers

        for row in fetchers.fetch_indices():
            if row.get("code") == "sh000001" and row.get("changePct") is not None:
                return float(row["changePct"])
    except Exception:  # noqa: BLE001
        return None
    return None


def _hist_highest(date: str, lookback: int = 5) -> list[int]:
    dates = trade_calendar.trade_dates_ending_at(date, lookback + 1) or []
    out: list[int] = []
    for d in dates:
        if d == date:
            continue
        s = em.day_summary(d)
        if s and s.get("highest_consec") is not None:
            out.append(int(s["highest_consec"]))
    return out


def gather_readings(date: str) -> dict[str, Any]:
    """组装定档所需读数（纯计算，不调 LLM）。

    派生情绪指标半边走定稿日档案；亏钱效应 / 涨跌家数仍按需取（全量 facts 含题材树，预算不必整包）。
    """
    from . import settled_archive as sa

    prev = trade_calendar.prev_trade_date(date)
    summary = em.day_summary(date)
    metrics = sa.emotion_half(date, with_cycle=False)
    me = metrics.get("money_effect") or {}
    pr = metrics.get("promotion") or {}
    lg = metrics.get("ladder_gap") or {}
    try:
        le = market_facts.loss_effect(date, prev)
    except Exception as exc:  # noqa: BLE001
        le = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        brd = breadth.market_breadth(date)
    except Exception as exc:  # noqa: BLE001
        brd = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    p12 = None
    if pr.get("available"):
        tier = (pr.get("tiers") or {}).get("1进2") or {}
        p12 = tier.get("rate")

    me_prev = pr_prev = le_prev = None
    p12_prev = med_prev = mld_prev = None
    if prev:
        try:
            m_prev = sa.emotion_half(prev, with_cycle=False)
            me_prev = m_prev.get("money_effect") or {}
            pr_prev = m_prev.get("promotion") or {}
            if me_prev.get("available"):
                med_prev = me_prev.get("median")
            if pr_prev.get("available"):
                p12_prev = ((pr_prev.get("tiers") or {}).get("1进2") or {}).get("rate")
            le_prev = market_facts.loss_effect(prev)
            if le_prev.get("available"):
                mld_prev = le_prev.get("market_limit_down")
        except Exception:  # noqa: BLE001
            pass

    broken = summary.get("broken_rate") if summary else None
    highest = None
    if lg.get("available") and lg.get("highest") is not None:
        highest = int(lg["highest"])
    elif summary and summary.get("highest_consec") is not None:
        highest = int(summary["highest_consec"])

    up = down = None
    if brd.get("available"):
        up, down = brd.get("up"), brd.get("down")

    return {
        "summary_ok": summary is not None,
        "summary_reason": None if summary else "涨停池摘要不可用",
        "money_ok": bool(me.get("available")),
        "money_reason": me.get("reason"),
        "promotion_ok": bool(pr.get("available")),
        "promotion_reason": pr.get("reason"),
        "limit_up": None if not summary else summary.get("limit_up"),
        "highest": highest,
        "highest_hist": _hist_highest(date),
        "broken_rate": broken,
        "money_median": me.get("median") if me.get("available") else None,
        "money_median_prev": med_prev,
        "promotion_1to2": p12,
        "promotion_1to2_prev": p12_prev,
        "deep_loss_5_rate": le.get("deep_loss_5_rate") if le.get("available") else None,
        "market_limit_down": le.get("market_limit_down") if le.get("available") else None,
        "market_limit_down_prev": mld_prev,
        "up": up,
        "down": down,
        "index_pct": _index_pct_for(date),
        "breadth_ok": bool(brd.get("available")),
        "breadth_reason": brd.get("reason"),
        "prev_date": prev,
    }


def guard(
    date: str,
    *,
    budget: dict,
    account: dict,
    holdings: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """现仓 vs 上限、降档减仓顺序、当日亏损闸。HTTP 只传账户与持仓。"""
    holdings = holdings or []
    equity = account.get("equity")
    consts = account.get("constants") or {}
    out: dict[str, Any] = {
        "date": date,
        "budget": budget,
        "equity": equity,
        "constants": consts,
        "position": None,
        "reduce_order": [],
        "daily_loss": None,
        "block_new_long_reasons": list(budget.get("block_new_long_reasons") or []),
    }
    if not budget.get("available"):
        return out
    if equity is None or float(equity) <= 0:
        out["block_new_long_reasons"] = out["block_new_long_reasons"] + ["未录入总权益"]
        return out

    eq = float(equity)
    cap_t = float(budget["cap_total"])
    cap_s = float(budget["cap_single"])
    pos = tb.position_vs_caps(holdings, eq, cap_t, cap_s)
    out["position"] = pos
    out["reduce_order"] = tb.reduce_order(holdings, eq, cap_t)
    if pos.get("over_total"):
        out["block_new_long_reasons"].append("总仓已达当前档 Cap_total")

    prev = trade_calendar.prev_trade_date(date)
    snaps = account.get("snapshots") or {}
    prev_snap = snaps.get(prev) if prev else None
    if prev_snap and prev_snap.get("equity"):
        prev_eq = float(prev_snap["equity"])
        if prev_eq > 0:
            pnl_pct = (eq - prev_eq) / prev_eq
            limit = float(consts.get("daily_loss_limit") or tb.DEFAULT_DAILY_LOSS_LIMIT)
            hit = pnl_pct <= -limit
            out["daily_loss"] = {
                "prev_date": prev,
                "prev_equity": prev_eq,
                "equity": eq,
                "pnl_pct": round(pnl_pct, 4),
                "limit": limit,
                "hit": hit,
            }
            if hit:
                out["block_new_long_reasons"].append(
                    f"触及当日亏损限额（{pnl_pct:.2%} ≤ -{limit:.0%}）"
                )
    return out


def size_preview(
    date: str,
    *,
    budget: dict,
    account: dict,
    holdings: Optional[list[dict]] = None,
    stop_pct: float,
    boards: Optional[int] = None,
) -> dict[str, Any]:
    """单笔金额：预算 + 账户 + 现仓占用。HTTP 只做参数校验。"""
    holdings = holdings or []
    equity = account.get("equity")
    if not budget.get("available"):
        return {"ok": False, "reason": budget.get("reason") or "预算不可用", "amount": 0}
    if equity is None or float(equity) <= 0:
        return {"ok": False, "reason": "请先录入总权益", "amount": 0}

    used = sum(float(h.get("market_value") or 0) for h in holdings)
    risk = float((account.get("constants") or {}).get("risk_per_trade")
                 or tb.DEFAULT_RISK_PER_TRADE)
    result = tb.size_amount(
        float(equity),
        float(budget["cap_total"]),
        float(budget["cap_single"]),
        used,
        risk,
        stop_pct,
        boards=boards,
        phase=str(budget.get("phase") or "升温扩张"),
    )
    result["date"] = date
    result["phase"] = budget.get("phase")
    result["cap_total"] = budget.get("cap_total")
    result["cap_single"] = budget.get("cap_single")
    result["used"] = round(used, 2)
    return result
