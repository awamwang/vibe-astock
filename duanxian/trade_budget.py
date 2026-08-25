"""仓位预算 —— 情绪硬规则定档 + Cap + 单笔金额（不进 AI prompt）。

情绪管总仓/单票上限；本模块不选股、不下单。缺关键读数整日不可用，不给假 Cap。
"""

from __future__ import annotations

from typing import Any, Optional

# 六档（硬规则；与 LLM 五档词典刻意分开）
PHASES = (
    "冰点观察",
    "修复确认",
    "升温扩张",
    "高潮拥挤",
    "过热防守",
    "退潮杀伤",
)

# 宽度背离「降一档」：沿防守方向；修复确认只可由手拨进入，故不作为降档落点
_NEXT_DEFENSIVE = {
    "升温扩张": "高潮拥挤",
    "修复确认": "冰点观察",
    "高潮拥挤": "过热防守",
    "冰点观察": "退潮杀伤",
    "过热防守": "退潮杀伤",
    "退潮杀伤": "退潮杀伤",
}

# 总仓默认（文档区间低端）；单票默认 = 总仓 / 2，均可在自定义配置里分别覆盖
_CAP_TOTAL: dict[str, float] = {
    "冰点观察": 0.20,
    "修复确认": 0.40,
    "升温扩张": 0.60,
    "高潮拥挤": 0.40,
    "过热防守": 0.20,
    "退潮杀伤": 0.00,
}

_ACTIONS: dict[str, dict[str, list[str]]] = {
    "冰点观察": {
        "allow": ["分批试错", "低吸确认"],
        "forbid": ["追连板", "满仓梭哈"],
    },
    "修复确认": {
        "allow": ["主线首板/二板", "核心回踩"],
        "forbid": ["乱扫跟风杂毛"],
    },
    "升温扩张": {
        "allow": ["顺势加仓", "持有核心"],
        "forbid": ["逆势抄底杂毛"],
    },
    "高潮拥挤": {
        "allow": ["兑现部分", "降集中度"],
        "forbid": ["新开高位接力仓"],
    },
    "过热防守": {
        "allow": ["只减不加", "只做防守"],
        "forbid": ["任何扩张性开仓"],
    },
    "退潮杀伤": {
        "allow": ["空仓或极轻仓观望"],
        "forbid": ["抄底", "接飞刀"],
    },
}

_NO_EXPANSION = frozenset({"过热防守", "退潮杀伤", "高潮拥挤"})

DEFAULT_RISK_PER_TRADE = 0.005
DEFAULT_DAILY_LOSS_LIMIT = 0.02
DEFAULT_MAX_DD_SOFT = 0.08
DEFAULT_MAX_DD_HARD = 0.12

_BOARD_DISCOUNT = {1: 1.0, 2: 0.7}  # ≥3 → 0.4


def default_caps(phase: str) -> tuple[float, float]:
    """内置默认：总仓用硬规则表，单票为总仓一半。"""
    if phase not in _CAP_TOTAL:
        raise ValueError(f"未知档位 {phase!r}，只能是 {PHASES}")
    total = _CAP_TOTAL[phase]
    return total, round(total / 2.0, 4)


def default_prompt(phase: str) -> str:
    """内置提示词：由允许 / 禁止动作拼出。"""
    act = _ACTIONS[phase]
    lines: list[str] = []
    if act["allow"]:
        lines.append("允许：" + "、".join(act["allow"]))
    if act["forbid"]:
        lines.append("禁止：" + "、".join(act["forbid"]))
    return "\n".join(lines)


def _resolved(phase: str) -> dict[str, Any]:
    from . import trade_phase_config as tpc

    return tpc.row_for(phase)


def caps_for(phase: str) -> tuple[float, float]:
    if phase not in PHASES:
        raise ValueError(f"未知档位 {phase!r}，只能是 {PHASES}")
    row = _resolved(phase)
    return float(row["cap_total"]), float(row["cap_single"])


def prompt_for(phase: str) -> str:
    if phase not in PHASES:
        raise ValueError(f"未知档位 {phase!r}，只能是 {PHASES}")
    return str(_resolved(phase).get("prompt") or "")


def actions_for(phase: str) -> dict[str, list[str]]:
    return dict(_ACTIONS[phase])


def demote(phase: str) -> str:
    """宽度背离等：沿防守方向降一档，地板为退潮杀伤。"""
    return _NEXT_DEFENSIVE.get(phase, "退潮杀伤")


def board_discount(boards: Optional[int], phase: str) -> float:
    """板位折扣；高潮档再砍一半。未填板位按首板 1.0×。"""
    if boards is None or boards < 1:
        d = 1.0
    elif boards >= 3:
        d = 0.4
    else:
        d = _BOARD_DISCOUNT.get(int(boards), 1.0)
    if phase == "高潮拥挤":
        d *= 0.5
    return d


def size_amount(
    equity: float,
    cap_total: float,
    cap_single: float,
    used: float,
    risk_per_trade: float,
    stop_pct: float,
    boards: Optional[int] = None,
    phase: str = "升温扩张",
) -> dict[str, Any]:
    """单笔金额 = min(单票上限, 风险倒推, 剩余总仓) × 板位折扣。"""
    if equity <= 0:
        return {"ok": False, "reason": "权益须 > 0", "amount": 0.0}
    if stop_pct <= 0:
        return {"ok": False, "reason": "止损幅度须 > 0", "amount": 0.0}
    single = equity * cap_single
    by_risk = equity * risk_per_trade / stop_pct
    remain = max(equity * cap_total - max(used, 0.0), 0.0)
    raw = min(single, by_risk, remain)
    disc = board_discount(boards, phase)
    amount = round(raw * disc, 2)
    return {
        "ok": True,
        "amount": amount,
        "components": {
            "by_single_cap": round(single, 2),
            "by_risk": round(by_risk, 2),
            "remain_total": round(remain, 2),
            "board_discount": disc,
            "raw_before_discount": round(raw, 2),
        },
    }


def _f(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None  # noqa: PLR0124
    return None


def collect_gap_reasons(readings: dict) -> list[str]:
    """关键读数缺失原因；非空则整日预算不可用。"""
    gaps: list[str] = []
    if not readings.get("summary_ok"):
        gaps.append(readings.get("summary_reason") or "涨停生态三件套不可用")
    if not readings.get("money_ok"):
        gaps.append(readings.get("money_reason") or "赚钱效应不可用")
    if not readings.get("promotion_ok"):
        gaps.append(readings.get("promotion_reason") or "晋级率不可用")
    br = _f(readings.get("broken_rate"))
    if readings.get("summary_ok") and br is None:
        gaps.append("炸板率缺失")
    return gaps


def repair_proxy_met(readings: dict) -> dict[str, Any]:
    """修复确认代理：只提示，不自动升档。"""
    checks = []
    med = _f(readings.get("money_median"))
    med_prev = _f(readings.get("money_median_prev"))
    p12 = _f(readings.get("promotion_1to2"))
    p12_prev = _f(readings.get("promotion_1to2_prev"))
    ld = _f(readings.get("market_limit_down"))
    ld_prev = _f(readings.get("market_limit_down_prev"))

    money_ok = med is not None and med > 0 and (med_prev is None or med > med_prev)
    checks.append({"key": "赚钱效应中位转正/回升", "ok": bool(money_ok),
                   "detail": f"今日 {med}，昨 {med_prev}"})
    promo_ok = p12 is not None and (p12_prev is None or p12 > p12_prev)
    checks.append({"key": "1进2 回升", "ok": bool(promo_ok),
                   "detail": f"今日 {p12}，昨 {p12_prev}"})
    ld_ok = ld is not None and ld_prev is not None and ld < ld_prev
    if ld is None and ld_prev is None:
        checks.append({"key": "跌停减少", "ok": False, "detail": "跌停家数不可比"})
        ld_ok = False
    else:
        checks.append({"key": "跌停减少", "ok": bool(ld_ok),
                       "detail": f"今日 {ld}，昨 {ld_prev}"})
    return {"met": bool(money_ok and promo_ok and ld_ok), "checks": checks}


def width_divergence(readings: dict) -> dict[str, Any]:
    """指数涨 + 上涨家数弱 + 赚钱效应中位转负。"""
    idx = _f(readings.get("index_pct"))
    up = _f(readings.get("up"))
    down = _f(readings.get("down"))
    med = _f(readings.get("money_median"))
    if idx is None or up is None or down is None or med is None:
        return {"hit": False, "skipped": True,
                "reason": "宽度背离所需读数不全（指数涨跌或涨跌家数或赚钱效应）"}
    tot = up + down
    up_share = (up / tot) if tot > 0 else None
    weak = up_share is not None and up_share < 0.45
    hit = idx > 0 and weak and med < 0
    return {
        "hit": hit,
        "skipped": False,
        "index_pct": idx,
        "up_share": None if up_share is None else round(up_share, 3),
        "money_median": med,
    }


def _height_pressed(readings: dict) -> bool:
    """连板高度相对近窗回落。"""
    h = readings.get("highest")
    hist = readings.get("highest_hist") or []
    if not isinstance(h, int) or not hist:
        return False
    peak = max(hist)
    return peak >= h + 1 and peak >= 4


def _height_near_peak(readings: dict) -> bool:
    h = readings.get("highest")
    hist = readings.get("highest_hist") or []
    if not isinstance(h, int):
        return False
    if not hist:
        return h >= 5
    return h >= max(hist) and h >= 4


def classify_rule_phase(readings: dict) -> tuple[str, list[str]]:
    """定档。若读数带可用 S 且算法非硬规则，走 S 区间；否则纯涨停生态硬规则。"""
    from . import sentiment_score as ss

    s = _f(readings.get("s"))
    method = str(readings.get("s_method") or ss.METHOD_HARD)
    if s is not None and method != ss.METHOD_HARD and readings.get("s_ok"):
        return ss.classify_with_s(readings, s)

    reasons: list[str] = []
    h = int(readings.get("highest") or 0)
    br = _f(readings.get("broken_rate")) or 0.0
    med = _f(readings.get("money_median"))
    p12 = _f(readings.get("promotion_1to2"))
    zt = int(readings.get("limit_up") or 0)
    deep5 = _f(readings.get("deep_loss_5_rate"))
    mld = _f(readings.get("market_limit_down"))

    pressed = _height_pressed(readings)
    hurt = (
        br >= 0.40
        or (p12 is not None and p12 < 0.20)
        or (med is not None and med < 0)
        or (deep5 is not None and deep5 >= 0.25)
        or (mld is not None and mld >= 20)
    )
    if pressed and hurt:
        reasons.append("高度压降且炸板/晋级/赚钱效应/亏钱效应转差 → 退潮杀伤")
        return "退潮杀伤", reasons

    if _height_near_peak(readings) and br >= 0.40:
        reasons.append("高度仍处近窗高位且炸板率≥40% → 过热防守")
        return "过热防守", reasons

    if h >= 5 and med is not None and med >= 0:
        reasons.append("最高板≥5 且赚钱效应中位≥0 → 高潮拥挤")
        return "高潮拥挤", reasons

    ice = h <= 3 and (
        (med is not None and med < 0)
        or (p12 is not None and p12 < 0.15)
        or zt < 30
    )
    if ice:
        reasons.append("高度≤3 且赚钱效应差/晋级弱/涨停稀 → 冰点观察")
        return "冰点观察", reasons

    reasons.append("未命中防守/冰点/高潮条件 → 升温扩张")
    return "升温扩张", reasons


def build_budget(
    readings: dict,
    *,
    prev_rule_phase: Optional[str] = None,
    override_phase: Optional[str] = None,
    override_reason: Optional[str] = None,
) -> dict[str, Any]:
    """由读数生成一日预算。`prev_rule_phase` 仅供展示/代理上下文，不自动升档。"""
    gaps = collect_gap_reasons(readings)
    if gaps:
        return {
            "available": False,
            "reason": "；".join(gaps),
            "readings": readings,
            "rule_phase": None,
            "override_phase": override_phase,
            "override_reason": override_reason,
            "phase": None,
            "cap_total": None,
            "cap_single": None,
            "prompt": None,
            "allow": [],
            "forbid": [],
            "expansion_allowed": False,
            "width_divergence": None,
            "demoted": False,
            "classify_reasons": [],
            "repair_proxy": repair_proxy_met(readings),
            "prev_rule_phase": prev_rule_phase,
            "block_new_long_reasons": ["今日预算不可用：" + "；".join(gaps)],
        }

    rule, reasons = classify_rule_phase(readings)
    # 上一交易日已是冰点时，把修复代理写进理由（仍不自动升）
    proxy = repair_proxy_met(readings)
    if prev_rule_phase == "冰点观察":
        reasons.append(
            "上一交易日为冰点观察；修复代理"
            + ("已满足，可手拨「修复确认」" if proxy["met"] else "未满足，维持规则档")
        )

    wd = width_divergence(readings)
    phase = rule
    demoted = False
    if wd.get("hit"):
        phase = demote(phase)
        demoted = phase != rule
        reasons.append(
            f"宽度背离（指数涨、上涨占比弱、赚钱效应中位转负）→ 降档至 {phase}"
            if demoted else "宽度背离命中但已在防守地板"
        )

    if override_phase:
        if override_phase not in PHASES:
            return {
                "available": False,
                "reason": f"覆盖档位非法：{override_phase}",
                "readings": readings,
                "rule_phase": rule,
                "override_phase": override_phase,
                "override_reason": override_reason,
                "phase": None,
                "cap_total": None,
                "cap_single": None,
                "prompt": None,
                "allow": [],
                "forbid": [],
                "expansion_allowed": False,
                "width_divergence": wd,
                "demoted": demoted,
                "classify_reasons": reasons,
                "repair_proxy": proxy,
                "prev_rule_phase": prev_rule_phase,
                "block_new_long_reasons": [f"覆盖档位非法：{override_phase}"],
            }
        phase = override_phase

    cap_t, cap_s = caps_for(phase)
    act = actions_for(phase)
    prompt = prompt_for(phase)
    expansion = phase not in _NO_EXPANSION and phase != "冰点观察"
    # 冰点允许分批试错，但不算「扩张性开仓」；高潮/过热/退潮禁止新开扩张
    if phase == "冰点观察":
        expansion = False  # 试错用计算器，闸门仍标非扩张
    if phase == "修复确认":
        expansion = True

    blocks: list[str] = []
    if phase in ("过热防守", "退潮杀伤"):
        blocks.append(f"档位「{phase}」禁止扩张性开仓")
    if phase == "高潮拥挤":
        blocks.append("档位「高潮拥挤」禁止新开高位接力仓")
    if wd.get("hit") and demoted:
        blocks.append("宽度背离已降档，勿逆势加仓")

    return {
        "available": True,
        "reason": None,
        "readings": readings,
        "rule_phase": rule,
        "override_phase": override_phase,
        "override_reason": override_reason,
        "phase": phase,
        "cap_total": cap_t,
        "cap_single": cap_s,
        "prompt": prompt,
        "allow": act["allow"],
        "forbid": act["forbid"],
        "expansion_allowed": expansion,
        "width_divergence": wd,
        "demoted": demoted,
        "classify_reasons": reasons,
        "repair_proxy": proxy,
        "prev_rule_phase": prev_rule_phase,
        "block_new_long_reasons": blocks,
    }


def reduce_order(holdings: list[dict], equity: float, cap_total: float) -> list[dict]:
    """降档后：按浮盈从差到好列出需压到新总仓上限内的减仓顺序。"""
    if equity <= 0:
        return []
    limit = equity * cap_total
    rows = []
    for h in holdings:
        mv = float(h.get("market_value") or 0)
        pnl = float(h.get("pnl") or 0)
        rows.append({
            "code": h.get("code"),
            "name": h.get("name"),
            "market_value": round(mv, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": h.get("pnl_pct"),
        })
    rows.sort(key=lambda r: (r["pnl"], r["market_value"]))
    used = sum(r["market_value"] for r in rows)
    if used <= limit:
        return [{"code": r["code"], "name": r["name"], "market_value": r["market_value"],
                 "pnl": r["pnl"], "pnl_pct": r["pnl_pct"], "action": "无需减仓"}
                for r in rows]

    overflow = used - limit
    out = []
    left = overflow
    for r in rows:
        if left <= 0:
            out.append({**r, "action": "保留", "suggest_cut": 0.0})
            continue
        cut = min(r["market_value"], left)
        out.append({**r, "action": "建议减仓", "suggest_cut": round(cut, 2)})
        left -= cut
    return out


def position_vs_caps(
    holdings: list[dict],
    equity: float,
    cap_total: float,
    cap_single: float,
) -> dict[str, Any]:
    """现仓相对总仓/单票上限。"""
    mv = sum(float(h.get("market_value") or 0) for h in holdings)
    total_pct = (mv / equity) if equity > 0 else None
    breaches = []
    per = []
    for h in holdings:
        hm = float(h.get("market_value") or 0)
        pct = (hm / equity) if equity > 0 else None
        over = pct is not None and pct > cap_single + 1e-9
        per.append({
            "code": h.get("code"), "name": h.get("name"),
            "market_value": round(hm, 2),
            "pct_of_equity": None if pct is None else round(pct, 4),
            "over_single": over,
        })
        if over:
            breaches.append(f"{h.get('code')} 超单票上限")
    over_total = total_pct is not None and total_pct > cap_total + 1e-9
    if over_total:
        breaches.append("总仓超当前档上限")
    return {
        "market_value": round(mv, 2),
        "total_pct": None if total_pct is None else round(total_pct, 4),
        "over_total": over_total,
        "remain_total": round(max(equity * cap_total - mv, 0), 2) if equity > 0 else 0.0,
        "per_name": per,
        "breaches": breaches,
    }
