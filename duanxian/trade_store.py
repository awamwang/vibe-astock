"""仓位预算落盘与账户权益。

- 日预算：`~/.duanxian-agents/trade/{date}.json`（环境层，无私仓字段）
- 账户：`~/.vibe-research/trade_account.json`（权益、快照、可手改常量）
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from . import breadth, emotion_metrics as em, market_facts, trade_budget as tb
from . import trade_calendar
from .util import atomic_write_json, china_now

_TRADE_DIR = os.path.expanduser("~/.duanxian-agents/trade")
_ACCOUNT_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(
    os.path.expanduser("~"), ".vibe-research"
)
_ACCOUNT_FILE = os.path.join(_ACCOUNT_DIR, "trade_account.json")
_SCHEMA = 1
_LOCK = threading.Lock()

# 日快照 / 账户栏位：命名写入；同日覆盖
_ACCOUNT_FIELD_KEYS = (
    "account_name",
    "cash_balance",
    "account_display",
    "broker",
    "available",
    "withdrawable",
    "frozen",
    "stock_market_value",
    "position_pnl",
    "daily_pnl",
    "daily_pnl_pct",
)
_NUM_FIELD_KEYS = frozenset({
    "cash_balance", "available", "withdrawable", "frozen",
    "stock_market_value", "position_pnl", "daily_pnl", "daily_pnl_pct",
})


def _trade_path(date: str) -> str:
    return os.path.join(_TRADE_DIR, f"{date}.json")


def _default_account() -> dict:
    return {
        "schema": _SCHEMA,
        "equity": None,
        "equity_note": "",
        "account_fields": {},
        "updated_at": None,
        "snapshots": {},
        "constants": {
            "risk_per_trade": tb.DEFAULT_RISK_PER_TRADE,
            "daily_loss_limit": tb.DEFAULT_DAILY_LOSS_LIMIT,
            "max_dd_soft": tb.DEFAULT_MAX_DD_SOFT,
            "max_dd_hard": tb.DEFAULT_MAX_DD_HARD,
        },
    }


def _to_opt_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(v), 4 if abs(float(v)) < 1000 else 2)
    except (TypeError, ValueError):
        return None


def normalize_account_fields(raw: Optional[dict]) -> dict:
    """只保留已知栏位；数字统一 float，文本去空白。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in _ACCOUNT_FIELD_KEYS:
        if k not in raw:
            continue
        v = raw[k]
        if v is None or v == "":
            continue
        if k in _NUM_FIELD_KEYS:
            fv = _to_opt_float(v)
            if fv is not None:
                out[k] = fv
        else:
            s = str(v).strip()
            if s:
                out[k] = s
    return out


def format_account_summary(fields: Optional[dict], manual_note: str = "") -> str:
    """命名格式化摘要，例如：账户名…，资金余额…，右下角显示…｜来源:… · 可用… · …"""
    f = normalize_account_fields(fields)
    head: list[str] = []
    if f.get("account_name"):
        head.append(f"账户名{f['account_name']}")
    cash = f.get("cash_balance")
    if cash is None:
        cash = f.get("withdrawable")
    if cash is not None:
        head.append(f"资金余额{cash}")
    if f.get("account_display"):
        head.append(f"右下角显示{f['account_display']}")

    tail: list[str] = []
    if f.get("broker"):
        tail.append(f"来源:{f['broker']}")
    if f.get("available") is not None:
        tail.append(f"可用{f['available']}")
    mv = f.get("stock_market_value")
    if mv is not None:
        # 市值整数不带小数尾巴
        tail.append(f"市值{int(mv) if float(mv) == int(mv) else mv}")
    if f.get("daily_pnl") is not None:
        tail.append(f"当日盈亏{f['daily_pnl']}")
    if f.get("daily_pnl_pct") is not None:
        tail.append(f"当日盈亏比{f['daily_pnl_pct']}%")

    auto = ""
    if head and tail:
        auto = "，".join(head) + "｜" + " · ".join(tail)
    elif head:
        auto = "，".join(head)
    elif tail:
        auto = " · ".join(tail)

    manual = (manual_note or "").strip()
    if manual and auto:
        # 手工备注不重复整段自动摘要
        if manual == auto or auto in manual:
            return manual
        return f"{manual}｜{auto}" if "｜" not in manual else f"{manual} · {auto}"
    return manual or auto


def load_account() -> dict:
    try:
        with open(_ACCOUNT_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            return _default_account()
        base = _default_account()
        base.update({k: d[k] for k in base if k in d})
        if isinstance(d.get("constants"), dict):
            base["constants"] = {**base["constants"], **d["constants"]}
        if isinstance(d.get("snapshots"), dict):
            base["snapshots"] = d["snapshots"]
        if isinstance(d.get("account_fields"), dict):
            base["account_fields"] = normalize_account_fields(d["account_fields"])
        return base
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_account()


def save_account(d: dict) -> dict:
    os.makedirs(_ACCOUNT_DIR, exist_ok=True)
    d = dict(d)
    d["schema"] = _SCHEMA
    d["updated_at"] = china_now().strftime("%Y-%m-%d %H:%M:%S")
    atomic_write_json(_ACCOUNT_FILE, d)
    return d


def set_equity(equity: float, note: str = "", fields: Optional[dict] = None) -> dict:
    if equity < 0:
        raise ValueError("权益不能为负")
    with _LOCK:
        d = load_account()
        d["equity"] = round(float(equity), 2)
        if fields is not None:
            merged = {**(d.get("account_fields") or {}), **normalize_account_fields(fields)}
            d["account_fields"] = normalize_account_fields(merged)
        if note is not None:
            d["equity_note"] = str(note) if str(note).strip() else format_account_summary(
                d.get("account_fields") or {}
            )
        return save_account(d)


def set_account_fields(fields: dict, *, note: Optional[str] = None, replace: bool = False) -> dict:
    """更新账户结构化栏位；replace=True 整表替换，否则合并。"""
    with _LOCK:
        d = load_account()
        norm = normalize_account_fields(fields)
        if replace:
            d["account_fields"] = norm
        else:
            d["account_fields"] = normalize_account_fields({
                **(d.get("account_fields") or {}),
                **norm,
            })
        if note is not None:
            d["equity_note"] = str(note)
        elif not (d.get("equity_note") or "").strip():
            d["equity_note"] = format_account_summary(d.get("account_fields") or {})
        return save_account(d)


def set_constants(**kwargs: float) -> dict:
    allowed = {"risk_per_trade", "daily_loss_limit", "max_dd_soft", "max_dd_hard"}
    with _LOCK:
        d = load_account()
        c = dict(d.get("constants") or {})
        for k, v in kwargs.items():
            if k not in allowed:
                raise ValueError(f"未知常量 {k}")
            if v is None:
                continue
            fv = float(v)
            if fv < 0 or fv > 1:
                raise ValueError(f"{k} 须在 0~1（比例）")
            c[k] = fv
        d["constants"] = c
        return save_account(d)


def snapshot_equity(
    date: str,
    market_value: float,
    fields: Optional[dict] = None,
    *,
    note: Optional[str] = None,
) -> dict:
    """已收盘日写入权益快照（同日覆盖）。含命名账户栏位；v1 不自动执行 MaxDD。"""
    date = str(date)
    with _LOCK:
        d = load_account()
        eq = d.get("equity")
        if eq is None:
            return d
        # 未显式传入则沿用账户当前栏位
        src = normalize_account_fields(fields) if fields is not None else {}
        if not src:
            src = dict(d.get("account_fields") or {})
        elif fields is not None:
            # 显式传入时与账户栏位合并（传入优先），并回写账户
            merged = {**(d.get("account_fields") or {}), **src}
            src = normalize_account_fields(merged)
            d["account_fields"] = src

        mv = round(float(market_value), 2)
        if mv == 0 and src.get("stock_market_value") is not None:
            mv = round(float(src["stock_market_value"]), 2)

        snap: dict[str, Any] = {
            "equity": eq,
            "market_value": mv,
            "asof": china_now().strftime("%Y-%m-%d %H:%M:%S"),
            **src,
        }
        summary = format_account_summary(src, note or "")
        if summary:
            snap["summary"] = summary
            if note is not None or not (d.get("equity_note") or "").strip():
                d["equity_note"] = summary

        snaps = dict(d.get("snapshots") or {})
        snaps[date] = snap  # 同日整行覆盖
        d["snapshots"] = snaps
        return save_account(d)


def load_day(date: str) -> Optional[dict]:
    path = _trade_path(date)
    try:
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        if isinstance(env, dict) and env.get("schema") == _SCHEMA and env.get("date") == date:
            return env
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return None


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
    """组装定档所需读数（纯计算，不调 LLM）。"""
    prev = trade_calendar.prev_trade_date(date)
    summary = em.day_summary(date)
    metrics = em.build_metrics(date, with_cycle=False)
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

    # 对照前日（修复代理 / 可选）
    me_prev = pr_prev = le_prev = None
    p12_prev = med_prev = mld_prev = None
    if prev:
        try:
            m_prev = em.build_metrics(prev, with_cycle=False)
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


def compute_day(
    date: str,
    *,
    override_phase: Optional[str] = None,
    override_reason: Optional[str] = None,
    keep_override: bool = True,
) -> dict:
    """计算并返回日预算信封（未写盘）。"""
    existing = load_day(date) if keep_override else None
    if override_phase is None and existing and keep_override:
        override_phase = existing.get("override_phase")
        override_reason = existing.get("override_reason")

    prev = trade_calendar.prev_trade_date(date)
    prev_env = load_day(prev) if prev else None
    prev_rule = (prev_env or {}).get("rule_phase")

    readings = gather_readings(date)
    body = tb.build_budget(
        readings,
        prev_rule_phase=prev_rule,
        override_phase=override_phase,
        override_reason=override_reason,
    )
    return {
        "schema": _SCHEMA,
        "date": date,
        "generated_at": china_now().strftime("%Y-%m-%d %H:%M:%S"),
        **body,
    }


def refresh(date: str, *, force: bool = False, emit_hooks: bool = True) -> dict:
    """写入 `trade/{date}.json`。保留已有手拨覆盖。"""
    date = str(date)
    _ = force  # 接口保留：始终重算读数，覆盖档由 keep_override 保留
    env = compute_day(date, keep_override=True)
    os.makedirs(_TRADE_DIR, exist_ok=True)
    atomic_write_json(_trade_path(date), env)
    if emit_hooks:
        try:
            from . import hooks

            hooks.RUNNER.emit_budget(date, env)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 预算钩子派发失败（{date}）：{type(exc).__name__}: {exc}")
    return env


def set_override(date: str, phase: Optional[str], reason: str = "") -> dict:
    """人手覆盖当日档位；phase=None 清除覆盖。"""
    date = str(date)
    if phase is not None and phase not in tb.PHASES:
        raise ValueError(f"档位须为 {tb.PHASES} 之一")
    env = compute_day(
        date,
        override_phase=phase,
        override_reason=(reason or None) if phase else None,
        keep_override=False,
    )
    os.makedirs(_TRADE_DIR, exist_ok=True)
    atomic_write_json(_trade_path(date), env)
    return env


def get_or_compute(date: str) -> dict:
    env = load_day(date)
    if env is not None:
        return env
    return refresh(date)
