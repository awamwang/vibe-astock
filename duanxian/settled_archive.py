"""定稿日档案 —— 一场次上「发生了什么」的组装入口。

派生情绪指标（赚钱效应 / 分档晋级 / …）与客观事实（含题材树）同属定稿口径，
与打板情绪（`live_emotion`）分属不同概念（见 ADR-0001）。

本模块拥有：
  · 行情覆盖率闸门（原先 em 私有、被 mf 偷用）
  · 定稿池读入口（原先 em._settled_pool 与 mf._settled_rows 两份同文）
  · `archive(date)` 一次给出 emotion_metrics + market_facts

`data.get_*` / 分析师 / 预算只做投影；落盘 JSON 顶层键名不变。
"""

from __future__ import annotations

from typing import Any, Optional

# 行情覆盖率闸门。批量行情半死不活时只回来几只票，若照样出结论，就是拿
# 3 只票的表现冒充全体赚钱效应 —— 数字看着完全正常，是最难发现的一类错。
_COVERAGE_MIN = 0.5      # 低于此：判定不可用，如实说取不到
_COVERAGE_PARTIAL = 0.9  # 低于此：可用但标 partial，prompt/UI 都要提示样本不全


def coverage(vals: list[float], expected: int) -> dict:
    """样本覆盖情况。expected = 本该拿到的只数。"""
    rate = round(len(vals) / expected, 3) if expected else None
    return {
        "sample": len(vals),
        "expected_sample": expected,
        "coverage_rate": rate,
        "partial": bool(rate is not None and rate < _COVERAGE_PARTIAL),
    }


# 兼容旧私有名（测试 / 过渡期 monkeypatch）
_coverage = coverage


def settled_pool(date: str) -> Optional[list[dict]]:
    """`date` 那一场的**定稿记录**：昨日涨停股在 `date` 当天的表现。

    每行自带 `ret`（该股在 `date` 的涨跌幅）、`prev_boards`、`close`、`limit_price`
    —— 也就是说"昨天进去的人赚不赚钱"这一整段**不需要实时行情**也算得出。

    🔴 这条路必须**优先于实时行情**：实时行情只在"目标日就是最近已收盘那一场"
       那一小段时间内可用，一旦今天开盘，它就变成今天的价、算不了昨天那一场 ——
       于是"想看 07-29 的复盘"就永远看不到了（而这是复盘系统的基本功能）。
       定稿记录对任何历史日期都取得到（已收盘的读落盘缓存，否则走东财昨日涨停池）。

    ⚠️ 定稿记录只覆盖**昨日涨停**那批，不含昨日炸板股 ——
       用它算的块要如实说明少了炸板那一档，别默默当成 0。
    """
    from .data import fetch_prev_pool

    try:
        return fetch_prev_pool(date)
    except Exception:  # noqa: BLE001  取不到就退回实时那条路
        return None


def limit_pools(date: str) -> Optional[dict]:
    """一场次涨停 / 炸板 / 跌停三池（磁盘缓存在 market_facts）。

    派生情绪指标与客观事实共用这一入口，避免 em._zt_pool 再打一遍东财。
    """
    from . import market_facts as mf

    return mf.pools(date)


def emotion_half(date: str, *, with_cycle: bool = True) -> dict:
    """定稿日档案 · 派生情绪指标半边（形状同 `emotion_metrics.build_metrics`）。"""
    from . import emotion_metrics as em

    return em.build_metrics(date, with_cycle=with_cycle)


def theme_tree_of(date: str, **kwargs) -> dict:
    """题材事件树：档案内唯一 build 入口（读时补树 / 周报现场补洞都走这里）。"""
    from . import theme_tree as tt

    return tt.build(date, **kwargs)


def facts_half(date: str) -> dict:
    """定稿日档案 · 客观事实半边（形状同原 `data.get_market_facts` 结构化部分）。"""
    from . import breadth as bd
    from . import market_facts as mf
    from . import stats_context as sctx

    return {
        "breadth": bd.market_breadth(date),
        "stats_context": sctx.context_for(date),
        "day_diff": sctx.diff(date),
        "trend": sctx.trend(10, end=date),
        "theme_tree": theme_tree_of(date),
        "seal_quality": mf.seal_quality(date),
        "loss_effect": mf.loss_effect(date),
        "feedback_matrix": mf.feedback_matrix(date),
        "theme_structure": mf.theme_structure(date),
        "event_ledger": mf.event_ledger(date),
        "by_board": mf.by_board(date),
    }


def archive(date: str, *, with_cycle: bool = True) -> dict[str, Any]:
    """一场次的定稿市场真相：派生情绪指标 + 客观事实（含题材树）。"""
    return {
        "date": date,
        "emotion_metrics": emotion_half(date, with_cycle=with_cycle),
        "market_facts": facts_half(date),
    }


def render_for_prompt(arch: dict) -> tuple[str, str]:
    """(metrics_text, facts_text) —— 分析师 prompt 投影。"""
    from . import emotion_metrics as em
    from .data import render_market_facts

    return (
        em.render_metrics(arch.get("emotion_metrics") or {}),
        render_market_facts(arch.get("market_facts") or {}),
    )
