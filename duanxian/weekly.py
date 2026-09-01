"""③ 多日情绪 + 龙头谱系。

- 多日情绪趋势：每日涨停家数 / 最高连板 / 炸板率 / 跌停家数（akshare 涨停池，按日）。
- 多日题材矩阵：优先读复盘落盘 `reviews/{date}.json` 里的 `market_facts.theme_tree`，
  没有复盘或树不可用再现场 `theme_tree.build()`；有几天展示几天。
- 龙头谱系：每日最高标龙头 + 该龙头此后每日的累计兑现（腾讯 hist，回答"前几天龙头现在怎么样"）。
数据源都不被封（akshare 涨停池 + 腾讯 hist）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from . import reflection
from . import trade_calendar

from . import fetchers as dr

from . import paths as _paths

_SHORT_BOARD_DIR = ""
_LIVE_EMOTION_DIR = ""


@_paths.register_rebind
def _rebind_paths() -> None:
    global _SHORT_BOARD_DIR, _LIVE_EMOTION_DIR
    _SHORT_BOARD_DIR = str(_paths.agents_dir() / "cache" / "short_board")
    _LIVE_EMOTION_DIR = str(_paths.agents_dir() / "cache" / "live_emotion")

_QCJ_LEVEL_ORD: dict[str, int] = {
    "冰点": 1, "修复": 2, "发酵": 3, "亢奋": 4, "退潮": 5,
}
_SPEC_ORD: dict[str, int] = {"冰点": 1, "普通": 2, "活跃": 3, "亢奋": 4}


def _last_trade_dates(n: int = 5) -> list[str]:
    """最近 n 个已收盘交易日（升序）。交易日历统一在 trade_calendar。"""
    return trade_calendar.last_trade_dates(n)


def _followthrough(code: str, appear_date: str, end_date: str) -> list[dict]:
    """龙头自 appear_date 收盘起，到 end_date 每日累计收益（%）。"""
    try:
        import akshare as ak

        sym = reflection._tx_symbol(code)
        df = ak.stock_zh_a_hist_tx(
            symbol=sym, start_date=appear_date.replace("-", ""), end_date=end_date.replace("-", "")
        )
        if df is None or len(df) == 0 or "close" not in df.columns:
            return []
        df = df.reset_index(drop=True)
        base: Optional[float] = None
        out = []
        for _, r in df.iterrows():
            dt = str(r["date"])
            c = float(r["close"])
            if dt == appear_date:
                base = c
            if base and base > 0 and dt >= appear_date:
                out.append({"date": dt, "cum_ret": round((c / base - 1) * 100, 2)})
        return out
    except Exception:
        return []


LINEAGE_SCHEMA = 3
WINDOW_DAYS_MAX = 15
WINDOW_DAYS_MIN = 7


def _clamp_window(n: int) -> int:
    return max(WINDOW_DAYS_MIN, min(WINDOW_DAYS_MAX, int(n or 10)))


def _canon_theme_tag(tag: str) -> str:
    """题材矩阵统计用 canonical 名（复盘快照里的旧写法也会归一）。"""
    from .theme_normalize import canonicalize_tag

    return canonicalize_tag(str(tag or "").strip())


def _merge_matrix_theme_rows(rows: list[dict]) -> list[dict]:
    """按 canonical 题材合并行（涨停数累加，最高板取 max）。"""
    merged: dict[str, dict] = {}
    for row in rows or []:
        tag = _canon_theme_tag(str(row.get("tag") or ""))
        if not tag:
            continue
        lu = int(row.get("limit_up") or 0)
        hi = int(row.get("highest") or 0)
        ld = int(row.get("limit_down") or 0)
        if tag not in merged:
            merged[tag] = {
                "tag": tag,
                "limit_up": 0,
                "highest": 0,
                "limit_down": 0,
                "state": str(row.get("state") or ""),
            }
        m = merged[tag]
        m["limit_up"] += lu
        m["highest"] = max(m["highest"], hi)
        m["limit_down"] += ld
    out = list(merged.values())
    out.sort(key=lambda x: (-x["limit_up"], -x["highest"], x["tag"]))
    return out


def _day_theme_tree(date: str, top_per_day: int = 12) -> tuple[dict, dict]:
    """(matrix_day, raw_tree) —— 复盘落盘 theme_tree 优先，没有再现场 build。"""
    try:
        from . import review_store as rs

        env = rs.load(date)
        if isinstance(env, dict):
            tree = (env.get("market_facts") or {}).get("theme_tree") or {}
            if tree.get("available"):
                return _matrix_day_from_tree(tree, top_per_day, source="review"), tree
    except Exception:  # noqa: BLE001
        pass
    from . import settled_archive as sa

    tree = sa.theme_tree_of(date)
    return _matrix_day_from_tree(tree, top_per_day, source="live"), tree


def _matrix_day_from_tree(tree: dict, top_per_day: int = 12, source: str = "live") -> dict:
    """把 theme_tree 快照转成矩阵单日结构。"""
    if not tree.get("available"):
        return {
            "available": False,
            "reason": tree.get("reason") or "题材树不可用",
            "themes": [],
            "source": source,
        }
    themes = []
    for row in tree.get("themes") or []:
        tag = str(row.get("tag") or "").strip()
        if not tag:
            continue
        themes.append({
            "tag": tag,
            "limit_up": int(row.get("limit_up") or 0),
            "state": str(row.get("state") or ""),
            "highest": int(row.get("highest") or 0),
            "limit_down": int(row.get("limit_down") or 0),
        })
    themes = _merge_matrix_theme_rows(themes)[:top_per_day]
    for i, row in enumerate(themes):
        row["rank"] = i + 1
    return {
        "available": True,
        "themes": themes,
        "tag_count": int(tree.get("tag_count") or len(themes)),
        "source": source,
    }


def build_theme_matrix(dates: list[str], top_per_day: int = 12) -> dict:
    """多日题材涨停矩阵 —— 按复盘 theme_tree 快照（优先）+ 现场补洞。"""
    by_day: dict[str, dict] = {}
    window_scores: dict[str, int] = {}
    last_3 = dates[-3:] if len(dates) >= 3 else list(dates)
    scores_3d: dict[str, int] = {}

    for d in dates:
        day, _tree = _day_theme_tree(d, top_per_day)
        by_day[d] = day
        if not day.get("available"):
            continue
        for row in day.get("themes") or []:
            tag = _canon_theme_tag(str(row.get("tag") or ""))
            if not tag:
                continue
            lu = int(row.get("limit_up") or 0)
            window_scores[tag] = window_scores.get(tag, 0) + lu
            if d in last_3:
                scores_3d[tag] = scores_3d.get(tag, 0) + lu

    def _rank_list(scores: dict[str, int], limit: int = 12) -> list[dict]:
        return [
            {"tag": tag, "score": score}
            for tag, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]
        ]

    return {
        "days": list(dates),
        "by_day": by_day,
        "rank_3d": _rank_list(scores_3d),
        "rank_window": _rank_list(window_scores),
        "available_days": sum(1 for d in dates if (by_day.get(d) or {}).get("available")),
        "total_days": len(dates),
        "review_days": sum(1 for d in dates if (by_day.get(d) or {}).get("source") == "review"),
    }


def merge_theme_matrix(dates: list[str], existing: dict | None = None, top_per_day: int = 12) -> dict:
    """补全题材矩阵：已有可用日保留，缺的读复盘/现场重搭。"""
    existing = existing or {}
    by_day: dict[str, dict] = dict(existing.get("by_day") or {})
    for d in dates:
        cur = by_day.get(d) or {}
        if cur.get("available") and cur.get("themes"):
            continue
        day, _tree = _day_theme_tree(d, top_per_day)
        by_day[d] = day

    last_3 = dates[-3:] if len(dates) >= 3 else list(dates)
    avail = sum(1 for d in dates if (by_day.get(d) or {}).get("available"))
    return {
        "days": list(dates),
        "by_day": by_day,
        "rank_3d": _rank_from_by_day(by_day, last_3),
        "rank_window": _rank_from_by_day(by_day, dates),
        "available_days": avail,
        "total_days": len(dates),
        "review_days": sum(1 for d in dates if (by_day.get(d) or {}).get("source") == "review"),
    }


def _normalize_matrix_by_day(by_day: dict[str, dict]) -> dict[str, dict]:
    """旧缓存里的题材名按当前别名表重算并合并。"""
    out: dict[str, dict] = {}
    for d, day in (by_day or {}).items():
        if not isinstance(day, dict):
            out[d] = day
            continue
        themes = _merge_matrix_theme_rows(day.get("themes") or [])
        out[d] = {**day, "themes": themes}
    return out


def _matrix_with_normalized_ranks(by_day: dict[str, dict], dates: list[str]) -> dict:
    """归一 by_day 后重算窗口 / 3 日排名。"""
    norm = _normalize_matrix_by_day(by_day)
    last_3 = dates[-3:] if len(dates) >= 3 else list(dates)
    avail = sum(1 for d in dates if (norm.get(d) or {}).get("available"))
    return {
        "days": list(dates),
        "by_day": norm,
        "rank_3d": _rank_from_by_day(norm, last_3),
        "rank_window": _rank_from_by_day(norm, dates),
        "available_days": avail,
        "total_days": len(dates),
    }


def ensure_theme_matrix(payload: dict) -> dict:
    """读缓存时补题材矩阵：旧版 weekly 没有该字段，或日期列与矩阵不同步。"""
    dates = [str(d.get("date") or "") for d in (payload.get("days") or []) if d.get("date")]
    if not dates:
        return payload
    matrix = payload.get("theme_matrix") or {}
    by_day = matrix.get("by_day") if isinstance(matrix.get("by_day"), dict) else {}
    if not by_day:
        merged = merge_theme_matrix(dates, None)
        return {**payload, "theme_matrix": {
            **merged,
            **_matrix_with_normalized_ranks(merged.get("by_day") or {}, dates),
            "review_days": merged.get("review_days"),
        }}
    missing = [d for d in dates if d not in by_day]
    if missing:
        merged = merge_theme_matrix(dates, matrix)
        return {**payload, "theme_matrix": {
            **merged,
            **_matrix_with_normalized_ranks(merged.get("by_day") or {}, dates),
            "review_days": merged.get("review_days"),
        }}
    aligned = _matrix_with_normalized_ranks(by_day, dates)
    return {**payload, "theme_matrix": {
        **matrix,
        **aligned,
        "review_days": matrix.get("review_days"),
    }}


def peak_drawdown(series: list[dict]) -> tuple[Optional[float], Optional[float]]:
    """(区间最高累计收益, 现价距该最高点的跌幅%)。两者都以**收盘价**口径"""
    vals = [s["cum_ret"] for s in (series or [])
            if isinstance(s.get("cum_ret"), (int, float))]
    if len(vals) < 2:
        return (None, None)
    peak = max(vals)
    cur = vals[-1]
    if 1 + peak / 100 <= 0:      # 理论上到不了（跌 100%），但除零要防
        return (round(peak, 2), None)
    dd = ((1 + cur / 100) / (1 + peak / 100) - 1) * 100
    # 浮点噪声会让"就在最高点"渲染成 -0.00%，钳到 0
    return (round(peak, 2), round(min(dd, 0.0), 2))


def build_weekly(n: int = 10) -> dict:
    window = _clamp_window(n)
    dates = _last_trade_dates(window)
    if not dates:
        return {"error": "取交易日历失败", "days": [], "leader_lineage": [], "theme_matrix": {}}

    daily = []
    for d in dates:
        try:
            zt = dr.fetch_zt_pool(d.replace("-", ""))
            if zt.get("error_zt") or zt.get("zt") is None:
                daily.append({"date": d, "limit_up": None, "broken_rate": None,
                              "highest_consec": None, "limit_down": None,
                              "leader": None, "unavailable": True})
                continue
            ztdf = zt.get("zt")
            n_zt = int(len(ztdf))
            hc = int(zt.get("highest_consec", 0) or 0)
            n_dt = int(zt.get("dt_count", 0) or 0)
            if zt.get("error_zb"):  # 炸板池失败 → 炸板率不可知，不算 0
                br = None
            else:
                n_zb = int(zt.get("zb_count", 0) or 0)
                br = round(n_zb / (n_zb + n_zt), 3) if (n_zb + n_zt) else 0
            ladder = zt.get("ladder", [])
            top = ladder[0] if ladder else None
            daily.append({
                "date": d, "limit_up": n_zt, "broken_rate": br, "highest_consec": hc,
                "limit_down": n_dt,
                "leader": ({"code": top["code"], "name": top["name"],
                            "boards": top["consec_boards"], "sector": top.get("sector", "")}
                           if top else None),
            })
        except Exception as exc:  # noqa: BLE001  单日彻底失败不拖累整周
            daily.append({"date": d, "error": type(exc).__name__, "limit_up": None,
                          "broken_rate": None, "highest_consec": None, "limit_down": None,
                          "leader": None, "unavailable": True})

    current_top_code = None
    for row in reversed(daily):
        if row.get("leader"):
            current_top_code = row["leader"]["code"]
            break

    # 龙头谱系：每个"当日最高标龙头"（去重，取其最早出现日）+ 此后走势
    lineage = []
    seen = set()
    end_date = dates[-1]
    for row in daily:
        ld = row.get("leader")
        if not ld or ld["code"] in seen:
            continue
        seen.add(ld["code"])
        series = _followthrough(ld["code"], row["date"], end_date)
        cum = series[-1]["cum_ret"] if series else None
        peak, drawdown = peak_drawdown(series)
        lineage.append({
            "code": ld["code"], "name": ld["name"], "sector": ld["sector"],
            "appear_date": row["date"], "boards_then": ld["boards"],
            "cum_return_since": cum, "series": series,
            "peak_cum_ret": peak, "drawdown_from_peak": drawdown,
            "is_current_top": ld["code"] == current_top_code,
        })

    theme_matrix = build_theme_matrix(dates)
    return {
        "days": daily,
        "leader_lineage": lineage,
        "lineage_schema": LINEAGE_SCHEMA,
        "window_days": window,
        "theme_matrix": theme_matrix,
    }


def _rank_from_by_day(by_day: dict[str, dict], dates_subset: list[str], limit: int = 12) -> list[dict]:
    scores: dict[str, int] = {}
    for d in dates_subset:
        day = by_day.get(d) or {}
        if not day.get("available"):
            continue
        for row in day.get("themes") or []:
            tag = _canon_theme_tag(str(row.get("tag") or ""))
            if tag:
                scores[tag] = scores.get(tag, 0) + int(row.get("limit_up") or 0)
    return [
        {"tag": tag, "score": score}
        for tag, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]


def _load_day_archive(cache_dir: str, date: str) -> dict:
    path = os.path.join(cache_dir, f"{date}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _parse_activity_pct(text: object) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return float(m.group(1)) if m else None


def _theme_speculation(limit_up: Optional[int], broken_rate: Optional[float]) -> tuple[Optional[str], Optional[int]]:
    if limit_up is None:
        return None, None
    lu = int(limit_up)
    br = broken_rate
    if lu >= 80:
        theme = "亢奋" if (br is not None and br < 0.30) else "活跃"
    elif lu >= 50:
        theme = "活跃"
    elif lu >= 25:
        theme = "普通"
    else:
        theme = "冰点"
    return theme, _SPEC_ORD.get(theme)


def _first_num(*vals: object) -> Optional[float]:
    for v in vals:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _coalesce_count(*vals: object) -> Optional[float]:
    """涨停/跌停家数：东财跌停池取数失败时常落 0，不阻断后续源（与短线盘面趣财经/开盘啦对齐）。"""
    zero: Optional[float] = None
    for v in vals:
        if v is None or v == "":
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
        if zero is None:
            zero = n
    return zero


def _day_metric_row(date: str) -> dict[str, Any]:
    """单日指标（优先复盘落盘 + 本地归档，历史日零网络）。"""
    from . import breadth as br
    from . import emotion_metrics as em
    from . import review_store as rs
    from . import settled_archive as sa
    from .data import fetch_prev_pool

    sb = _load_day_archive(_SHORT_BOARD_DIR, date)
    le = _load_day_archive(_LIVE_EMOTION_DIR, date)
    summary = em.day_summary(date) or {}
    rev = rs.load(date) or {}
    em_m = rev.get("emotion_metrics") or {}
    mf = rev.get("market_facts") or {}

    me = em_m.get("money_effect") if em_m.get("money_effect", {}).get("available") else {}
    if not me or me.get("median") is None:
        cached_pool = fetch_prev_pool(date)
        if cached_pool:
            vals = [r["ret"] for r in cached_pool if r.get("ret") is not None]
            if vals:
                from statistics import median

                me = {
                    **(me or {}),
                    "median": round(median(vals), 2),
                    "open_success_rate": me.get("open_success_rate") if me else None,
                    "close_success_rate": me.get("close_success_rate") if me else None,
                }
    if not me or me.get("median") is None:
        settled = sa.settled_pool(date)
        if settled:
            vals = [r["ret"] for r in settled if r.get("ret") is not None]
            if vals:
                from statistics import median

                me = {"median": round(median(vals), 2)}

    pr = em_m.get("promotion") if em_m.get("promotion", {}).get("available") else {}
    promo_rate = (pr.get("overall") or {}).get("rate")
    if promo_rate is None and le.get("promotion_rate") is not None:
        promo_rate = le.get("promotion_rate")

    cp = em_m.get("consec_premium") if em_m.get("consec_premium", {}).get("available") else {}
    cp_med = cp.get("median")

    loss = mf.get("loss_effect") if mf.get("loss_effect", {}).get("available") else {}
    loss_rate = loss.get("deep_loss_5_rate") if loss.get("available") else None
    if loss_rate is None:
        settled = sa.settled_pool(date)
        if settled:
            got = [r for r in settled if r.get("ret") is not None]
            if got:
                loss_rate = round(sum(1 for r in got if r["ret"] <= -5) / len(got), 3)

    breadth = mf.get("breadth") if mf.get("breadth", {}).get("available") else br.market_breadth(date)
    if not breadth.get("available"):
        breadth = {}

    limit_up = _coalesce_count(sb.get("qcj_zt"), sb.get("n_sjzt"), le.get("zt_count"), summary.get("limit_up"))
    limit_down = _coalesce_count(sb.get("qcj_dt"), sb.get("n_sjdt"), le.get("dt_count"))
    broken_rate = summary.get("broken_rate")
    if broken_rate is None and sb.get("broken_r") is not None:
        broken_rate = float(sb["broken_r"]) / 100.0
    if broken_rate is None and le.get("break_rate") is not None:
        broken_rate = le.get("break_rate")

    n_up = _first_num(breadth.get("up"), sb.get("n_up"))
    n_down = _first_num(breadth.get("down"), sb.get("n_down"))
    activity_pct = _parse_activity_pct(sb.get("activity"))
    if activity_pct is None and n_up is not None and n_down is not None and (n_up + n_down) > 0:
        activity_pct = round(n_up / (n_up + n_down) * 100, 1)

    spec_text, spec_ord = _theme_speculation(
        int(limit_up) if limit_up is not None else None,
        broken_rate if broken_rate is not None else None,
    )

    qcj_level = sb.get("qcj_level")
    qcj_ord = _QCJ_LEVEL_ORD.get(str(qcj_level or "").strip())

    amount_yi = _first_num(breadth.get("amount_yi"))
    if amount_yi is None and sb.get("v_ca") is not None:
        amount_yi = round(float(sb["v_ca"]) / 1e8, 1)

    m_net_yi = None
    if sb.get("m_net") is not None:
        m_net_yi = round(float(sb["m_net"]) / 1e8, 2)

    zt_premium = sb.get("zt_avg_zr")
    universe = _first_num(breadth.get("universe"))
    flat = _first_num(breadth.get("flat"))

    return {
        "temperature": sb.get("temperature"),
        "qcj_temp": sb.get("qcj_temp"),
        "activity_pct": activity_pct,
        "speculation": spec_text,
        "speculation_ord": spec_ord,
        "qcj_level": qcj_level,
        "qcj_level_ord": qcj_ord,
        "up": n_up,
        "down": n_down,
        "flat": flat,
        "universe": universe,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "deep_up_5": br.up5_of(breadth) if breadth else None,
        "deep_down_5": breadth.get("deep_down_5") if breadth else None,
        "broken_rate": broken_rate,
        "never_broken_rate": summary.get("never_broken_rate"),
        "zt_premium_pct": zt_premium,
        "open_success_rate": me.get("open_success_rate"),
        "close_success_rate": me.get("close_success_rate") or me.get("positive_rate"),
        "amount_yi": amount_yi,
        "m_net_yi": m_net_yi,
        "highest_board": _first_num(le.get("max_boards"), summary.get("highest_consec")),
        "lianban_count": le.get("lianban_count"),
        "promotion_rate": promo_rate,
        "money_effect_median": me.get("median"),
        "loss_effect_rate": loss_rate,
        "consec_premium_median": cp_med,
    }


def _market_total(row: dict) -> Optional[float]:
    u = row.get("universe")
    if u is not None and float(u) > 0:
        return float(u)
    up, down, flat = row.get("up"), row.get("down"), row.get("flat")
    if up is not None and down is not None and flat is not None:
        total = float(up) + float(down) + float(flat)
        return total if total > 0 else None
    return None


def _chart_series(rows: list[dict], key: str, *, kind: str, label: str,
                  label_key: Optional[str] = None, y_axis_index: int = 0,
                  plot_scale: Optional[float] = None) -> dict:
    out_vals: list[Any] = []
    out_labels: list[Optional[str]] = []
    for row in rows:
        v = row.get(key)
        out_vals.append(v if v is not None else None)
        if label_key:
            lv = row.get(label_key)
            out_labels.append(str(lv) if lv not in (None, "") else None)
        else:
            out_labels.append(None)
    out: dict[str, Any] = {
        "key": key, "label": label, "kind": kind, "values": out_vals,
        "labels": out_labels if any(x is not None for x in out_labels) else None,
        "y_axis_index": y_axis_index,
    }
    if plot_scale is not None and plot_scale != 1:
        out["plot_scale"] = plot_scale
    return out


def _chart_series_count_ratio(
    rows: list[dict], key: str, *, label: str, ratio_kind: str = "permille",
    y_axis_index: int = 0,
) -> dict:
    """家数序列：折线用占比，悬停展示「家数(占比)」。"""
    values: list[Any] = []
    counts: list[Any] = []
    totals: list[Any] = []
    for row in rows:
        n = row.get(key)
        total = _market_total(row)
        counts.append(int(n) if n is not None else None)
        totals.append(total)
        if n is None or total is None or total <= 0:
            values.append(None)
        elif ratio_kind == "permille":
            values.append(round(float(n) / total * 1000, 3))
        else:
            values.append(round(float(n) / total * 100, 3))
    kind = "permille" if ratio_kind == "permille" else "count_pct"
    return {
        "key": key, "label": label, "kind": kind, "values": values,
        "counts": counts, "totals": totals, "y_axis_index": y_axis_index,
    }


def build_metric_charts(dates: list[str]) -> dict:
    """多日指标分组图表数据（按类型与纵轴范围归并）。"""
    if not dates:
        return {"available": False, "reason": "无交易日", "days": [], "charts": []}
    rows = [{"date": d, **_day_metric_row(d)} for d in dates]
    charts = [
        {
            "id": "emotion_heat",
            "title": "情绪温度 · 情绪分 · 活跃度",
            "chart_type": "line",
            "y_axis": {"name": "分 / %", "kind": "count"},
            "series": [
                _chart_series(rows, "temperature", kind="count", label="情绪温度"),
                _chart_series(rows, "qcj_temp", kind="count", label="情绪分°"),
                _chart_series(rows, "activity_pct", kind="pct", label="活跃度"),
            ],
        },
        {
            "id": "stage_spec",
            "title": "阶段 · 题材投机",
            "chart_type": "bar",
            "y_axis": {"name": "档位", "kind": "ordinal"},
            "series": [
                _chart_series(rows, "qcj_level_ord", kind="ordinal", label="阶段",
                              label_key="qcj_level"),
                _chart_series(rows, "speculation_ord", kind="ordinal", label="题材投机",
                              label_key="speculation"),
            ],
        },
        {
            "id": "breadth_counts",
            "title": "上涨数 · 下跌数 · 深涨跌",
            "chart_type": "line",
            "y_axis": {"name": "%", "kind": "count_pct"},
            "series": [
                _chart_series_count_ratio(rows, "up", label="上涨数", ratio_kind="count_pct"),
                _chart_series_count_ratio(rows, "down", label="下跌数", ratio_kind="count_pct"),
                _chart_series_count_ratio(rows, "deep_up_5", label="涨幅≥5%", ratio_kind="count_pct"),
                _chart_series_count_ratio(rows, "deep_down_5", label="跌超5%", ratio_kind="count_pct"),
            ],
        },
        {
            "id": "limit_board",
            "title": "涨停 · 跌停 · 最高板 · 连板",
            "chart_type": "line",
            "y_axis": [
                {"name": "‰", "kind": "permille"},
                {"name": "板", "kind": "board"},
            ],
            "series": [
                _chart_series_count_ratio(rows, "limit_up", label="涨停数"),
                _chart_series_count_ratio(rows, "limit_down", label="跌停数"),
                _chart_series_count_ratio(rows, "lianban_count", label="连板数"),
                _chart_series(rows, "highest_board", kind="board", label="最高板数", y_axis_index=1),
            ],
        },
        {
            "id": "board_quality_rates",
            "title": "炸板率 · 封板率 · 晋级 · 涨停溢价",
            "chart_type": "line",
            "y_axis": {"name": "%", "kind": "rate"},
            "note": "涨停溢价折线按涨跌幅×10 绘制（与同图炸板率等同轴对比），悬停为真实百分比。",
            "series": [
                _chart_series(rows, "broken_rate", kind="rate", label="炸板率"),
                _chart_series(rows, "never_broken_rate", kind="rate", label="涨停未炸板比例"),
                _chart_series(rows, "promotion_rate", kind="rate", label="晋级率"),
                _chart_series(rows, "zt_premium_pct", kind="pct", label="涨停溢价", plot_scale=10),
            ],
        },
        {
            "id": "money_effect",
            "title": "赚钱效应 · 亏钱效应 · 连板溢价 · 打板成功率",
            "chart_type": "line",
            "y_axis": {"name": "%", "kind": "pct"},
            "note": "赚钱效应、连板溢价按涨跌幅×10 绘制（与亏钱效应/打板成功率同轴对比），悬停为真实百分比。",
            "series": [
                _chart_series(rows, "money_effect_median", kind="pct", label="赚钱效应", plot_scale=10),
                _chart_series(rows, "loss_effect_rate", kind="rate", label="亏钱效应"),
                _chart_series(rows, "consec_premium_median", kind="pct", label="连板溢价", plot_scale=10),
                _chart_series(rows, "open_success_rate", kind="rate", label="打板成功率-开盘"),
                _chart_series(rows, "close_success_rate", kind="rate", label="打板成功率-收盘"),
            ],
        },
        {
            "id": "amount",
            "title": "两市成交额",
            "chart_type": "line",
            "y_axis": {"name": "亿", "kind": "yi"},
            "series": [
                _chart_series(rows, "amount_yi", kind="yi", label="两市成交额"),
            ],
        },
        {
            "id": "main_flow",
            "title": "主力净流入",
            "chart_type": "line",
            "y_axis": {"name": "亿", "kind": "yi"},
            "series": [
                _chart_series(rows, "m_net_yi", kind="yi", label="主力净流入"),
            ],
        },
    ]
    has_any = any(
        v is not None
        for row in rows
        for k, v in row.items()
        if k != "date"
    )
    return {
        "available": has_any,
        "reason": None if has_any else "指标归档与缓存暂不可用",
        "days": dates,
        "charts": charts,
    }


def ensure_metric_charts(payload: dict) -> dict:
    """按窗口日期补全指标图表（读缓存时现场算，不污染 weekly 落盘结构）。"""
    dates = [str(d.get("date") or "") for d in (payload.get("days") or []) if d.get("date")]
    if not dates:
        return payload
    charts = build_metric_charts(dates)
    return {**payload, "metric_charts": charts}


def slice_weekly(payload: dict, days: int) -> dict:
    """按请求窗口裁剪已缓存的多日数据。"""
    want = _clamp_window(days)
    stored_days = [str(d.get("date") or "") for d in (payload.get("days") or []) if d.get("date")]
    if len(stored_days) <= want:
        return {**payload, "window_days": want}
    dates = stored_days[-want:]
    out = dict(payload)
    out["window_days"] = want
    out["days"] = [r for r in (payload.get("days") or []) if r.get("date") in dates]
    matrix = payload.get("theme_matrix") or {}
    if isinstance(matrix, dict) and matrix.get("by_day"):
        by_day = {d: matrix["by_day"][d] for d in dates if d in matrix["by_day"]}
        out["theme_matrix"] = {
            **matrix,
            **_matrix_with_normalized_ranks(by_day, dates),
        }
    elif dates:
        merged = merge_theme_matrix(dates)
        out["theme_matrix"] = {
            **merged,
            **_matrix_with_normalized_ranks(merged.get("by_day") or {}, dates),
        }
    return out
