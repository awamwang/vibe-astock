"""③ 多日情绪 + 龙头谱系。

- 多日情绪趋势：每日涨停家数 / 最高连板 / 炸板率 / 跌停家数（akshare 涨停池，按日）。
- 多日题材矩阵：优先读复盘落盘 `reviews/{date}.json` 里的 `market_facts.theme_tree`，
  没有复盘或树不可用再现场 `theme_tree.build()`；有几天展示几天。
- 龙头谱系：每日最高标龙头 + 该龙头此后每日的累计兑现（腾讯 hist，回答"前几天龙头现在怎么样"）。
数据源都不被封（akshare 涨停池 + 腾讯 hist）。
"""

from __future__ import annotations

from typing import Optional

from . import reflection
from . import trade_calendar

from . import fetchers as dr


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
    from . import theme_tree as tt

    tree = tt.build(date)
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
    for i, row in enumerate(tree.get("themes") or []):
        tag = str(row.get("tag") or "").strip()
        if not tag:
            continue
        themes.append({
            "tag": tag,
            "limit_up": int(row.get("limit_up") or 0),
            "state": str(row.get("state") or ""),
            "highest": int(row.get("highest") or 0),
            "limit_down": int(row.get("limit_down") or 0),
            "rank": i + 1,
        })
        if len(themes) >= top_per_day:
            break
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
            tag = str(row.get("tag") or "").strip()
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


def ensure_theme_matrix(payload: dict) -> dict:
    """读缓存时补题材矩阵：旧版 weekly 没有该字段，或日期列与矩阵不同步。"""
    dates = [str(d.get("date") or "") for d in (payload.get("days") or []) if d.get("date")]
    if not dates:
        return payload
    matrix = payload.get("theme_matrix") or {}
    by_day = matrix.get("by_day") if isinstance(matrix.get("by_day"), dict) else {}
    if not by_day:
        return {**payload, "theme_matrix": merge_theme_matrix(dates, None)}
    missing = [d for d in dates if d not in by_day]
    if missing:
        return {**payload, "theme_matrix": merge_theme_matrix(dates, matrix)}
    # 矩阵日期与窗口对齐
    if list(matrix.get("days") or []) != dates:
        last_3 = dates[-3:] if len(dates) >= 3 else list(dates)
        avail = sum(1 for d in dates if (by_day.get(d) or {}).get("available"))
        aligned = {
            **matrix,
            "days": dates,
            "by_day": {d: by_day[d] for d in dates if d in by_day},
            "rank_3d": _rank_from_by_day(by_day, last_3),
            "rank_window": _rank_from_by_day(by_day, dates),
            "available_days": avail,
            "total_days": len(dates),
        }
        return {**payload, "theme_matrix": aligned}
    return payload


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
            tag = str(row.get("tag") or "").strip()
            if tag:
                scores[tag] = scores.get(tag, 0) + int(row.get("limit_up") or 0)
    return [
        {"tag": tag, "score": score}
        for tag, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]


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
        last_3 = dates[-3:] if len(dates) >= 3 else list(dates)
        avail = sum(1 for d in dates if (by_day.get(d) or {}).get("available"))
        out["theme_matrix"] = {
            **matrix,
            "days": dates,
            "by_day": by_day,
            "rank_3d": _rank_from_by_day(by_day, last_3),
            "rank_window": _rank_from_by_day(by_day, dates),
            "available_days": avail,
            "total_days": len(dates),
        }
    elif dates:
        out["theme_matrix"] = merge_theme_matrix(dates)
    return out
