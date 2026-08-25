"""合成情绪分 S（0–100）—— 定档可选主输入。

算法界面可选，落盘 `~/.duanxian-agents/config/sentiment_s.json`。
`hard_rules`：不用 S，维持涨停生态硬规则树。
`qcj_degree`：趣财经 temperatureDegree 原样当 S。
`percentile_qcj_em`：趣财经 ~220 日序列 + 东财池补炸板/高度，分位等权合成。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from .util import atomic_write_json, china_now

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "sentiment_s.json")
_SERIES_PATH = os.path.expanduser("~/.duanxian-agents/cache/sentiment_s/series.json")
_SCHEMA = 1
_LOCK = threading.Lock()

METHOD_HARD = "hard_rules"
METHOD_QCJ = "qcj_degree"
METHOD_PCT = "percentile_qcj_em"

METHODS: dict[str, dict[str, str]] = {
    METHOD_HARD: {
        "label": "硬规则（无 S）",
        "desc": "只用涨停生态判定树，不计算合成分。当前默认。",
    },
    METHOD_QCJ: {
        "label": "趣财经情绪分°",
        "desc": "直接用趣财经 temperatureDegree（0–100）作为 S。",
    },
    METHOD_PCT: {
        "label": "历史分位（趣财经 + 东财）",
        "desc": "趣财经序列回拉 + 东财池补炸板率/最高连板，分位等权合成 0–100。",
    },
}

# 分位合成用的分量：越高越热；invert=True 表示原始值越大越冷
_PCT_FIELDS = (
    ("limit_up", False),
    ("limit_down", True),
    ("highest", False),
    ("broken_rate", True),
    ("qcj_temp", False),
)

_DEFAULT = {"schema": _SCHEMA, "method": METHOD_HARD}


class SentimentScoreError(ValueError):
    """情绪分配置非法。"""


def _read_config() -> dict:
    if not os.path.isfile(_CONFIG_PATH):
        return dict(_DEFAULT)
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return dict(_DEFAULT)
        method = str(env.get("method") or METHOD_HARD).strip()
        if method not in METHODS:
            method = METHOD_HARD
        return {"schema": _SCHEMA, "method": method}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT)


def get_method() -> str:
    return str(_read_config().get("method") or METHOD_HARD)


def set_method(method: str) -> dict:
    method = str(method or "").strip()
    if method not in METHODS:
        raise SentimentScoreError(f"未知算法 {method!r}，只能是 {tuple(METHODS)}")
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "method": method}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入情绪分配置失败：{_CONFIG_PATH}")
    return export_config()


def export_config() -> dict[str, Any]:
    cfg = _read_config()
    return {
        "schema": _SCHEMA,
        "path": _CONFIG_PATH,
        "method": cfg["method"],
        "methods": [
            {"id": mid, "label": meta["label"], "desc": meta["desc"]}
            for mid, meta in METHODS.items()
        ],
        "series_path": _SERIES_PATH,
        "series_meta": series_meta(),
    }


def series_meta() -> dict[str, Any]:
    env = _load_series()
    rows = env.get("rows") or []
    enriched = sum(1 for r in rows if r.get("em_ok"))
    return {
        "days": len(rows),
        "enriched_days": enriched,
        "first": rows[0]["date"] if rows else None,
        "last": rows[-1]["date"] if rows else None,
        "updated_at": env.get("updated_at"),
    }


def _load_series() -> dict:
    if not os.path.isfile(_SERIES_PATH):
        return {"schema": _SCHEMA, "rows": [], "updated_at": None}
    try:
        with open(_SERIES_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if isinstance(env, dict) and isinstance(env.get("rows"), list):
            return env
    except Exception:  # noqa: BLE001
        pass
    return {"schema": _SCHEMA, "rows": [], "updated_at": None}


def _save_series(rows: list[dict]) -> dict:
    os.makedirs(os.path.dirname(_SERIES_PATH), exist_ok=True)
    env = {
        "schema": _SCHEMA,
        "rows": rows,
        "updated_at": china_now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    atomic_write_json(_SERIES_PATH, env)
    return env


def _fetch_qcj_rows() -> list[dict]:
    """趣财经市场情绪整段序列（约 220 日）。"""
    import requests

    from .short_board import _QCJ_MARKET, _QCJ_UA

    r = requests.get(_QCJ_MARKET, headers=_QCJ_UA, timeout=20)
    r.raise_for_status()
    raw = r.json()
    rows = (raw.get("data") or {}).get("sentiment") or []
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            continue
        temp = row.get("temperatureDegree")
        zt = row.get("limitUpCount")
        dt = row.get("limitDownCount")
        consec = row.get("consecutiveLimitCount")
        try:
            qcj_temp = None if temp is None else float(temp)
        except (TypeError, ValueError):
            qcj_temp = None
        try:
            limit_up = None if zt is None else int(zt)
        except (TypeError, ValueError):
            limit_up = None
        try:
            limit_down = None if dt is None else int(dt)
        except (TypeError, ValueError):
            limit_down = None
        try:
            consec_n = None if consec is None else int(consec)
        except (TypeError, ValueError):
            consec_n = None
        out.append({
            "date": str(row["date"]),
            "qcj_temp": qcj_temp,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "consec_boards": consec_n,  # 连板家数（非最高板）；最高板靠东财补
            "level": str(row.get("sentimentLevel") or "") or None,
        })
    out.sort(key=lambda r: r["date"])
    return out


def _enrich_one(date: str) -> dict[str, Any]:
    """东财涨停生态：最高连板 + 炸板率。失败不抛，标 em_ok=False。"""
    from . import emotion_metrics as em

    try:
        s = em.day_summary(date)
    except Exception:  # noqa: BLE001
        s = None
    if not s:
        return {"highest": None, "broken_rate": None, "em_ok": False}
    return {
        "highest": s.get("highest_consec"),
        "broken_rate": s.get("broken_rate"),
        "em_ok": True,
    }


def refresh_series(*, enrich_limit: Optional[int] = None) -> dict[str, Any]:
    """回拉趣财经序列，按需用东财补炸板/高度；结果落盘。

    `enrich_limit`：本轮最多新补几天东财（None=缺什么补什么，首次会较慢）。
    """
    with _LOCK:
        qcj = _fetch_qcj_rows()
        if not qcj:
            raise RuntimeError("趣财经情绪序列为空")
        old = {r["date"]: r for r in (_load_series().get("rows") or []) if r.get("date")}
        merged: list[dict] = []
        pending = 0
        for row in qcj:
            d = row["date"]
            prev = old.get(d) or {}
            item = {
                **row,
                "highest": prev.get("highest"),
                "broken_rate": prev.get("broken_rate"),
                "em_ok": bool(prev.get("em_ok")),
            }
            need = not item["em_ok"] or item.get("highest") is None or item.get("broken_rate") is None
            if need and (enrich_limit is None or pending < enrich_limit):
                patch = _enrich_one(d)
                item["highest"] = patch["highest"]
                item["broken_rate"] = patch["broken_rate"]
                item["em_ok"] = patch["em_ok"]
                pending += 1
            # 最高板未补上时，退化为连板家数不合适；保持 None，分位时跳过该分量
            merged.append(item)
        env = _save_series(merged)
        return {
            "ok": True,
            "enriched_this_run": pending,
            "meta": series_meta(),
            "updated_at": env.get("updated_at"),
        }


def _percentile_rank(value: float, hist: list[float]) -> float:
    """值在样本中的分位 0–100（含自身）。样本不足返回 50。"""
    if not hist:
        return 50.0
    n = len(hist)
    less = sum(1 for x in hist if x < value)
    equal = sum(1 for x in hist if x == value)
    return round((less + 0.5 * equal) / n * 100.0, 2)


def _row_components(row: dict) -> dict[str, Optional[float]]:
    return {
        "limit_up": None if row.get("limit_up") is None else float(row["limit_up"]),
        "limit_down": None if row.get("limit_down") is None else float(row["limit_down"]),
        "highest": None if row.get("highest") is None else float(row["highest"]),
        "broken_rate": None if row.get("broken_rate") is None else float(row["broken_rate"]),
        "qcj_temp": None if row.get("qcj_temp") is None else float(row["qcj_temp"]),
    }


def _score_percentile(date: str, rows: list[dict]) -> dict[str, Any]:
    by = {r["date"]: r for r in rows}
    row = by.get(date)
    if not row:
        return {
            "available": False,
            "reason": f"分位序列中无 {date}（请先刷新序列）",
            "s": None,
            "method": METHOD_PCT,
        }
    comps = _row_components(row)
    hist_cols: dict[str, list[float]] = {k: [] for k, _ in _PCT_FIELDS}
    for r in rows:
        c = _row_components(r)
        for k, _inv in _PCT_FIELDS:
            if c[k] is not None:
                hist_cols[k].append(c[k])

    parts: list[float] = []
    detail: dict[str, Any] = {}
    for k, invert in _PCT_FIELDS:
        v = comps[k]
        hist = hist_cols[k]
        if v is None or len(hist) < 5:
            detail[k] = {"value": v, "pctile": None, "skipped": True}
            continue
        pct = _percentile_rank(v, hist)
        if invert:
            pct = round(100.0 - pct, 2)
        parts.append(pct)
        detail[k] = {"value": v, "pctile": pct, "skipped": False}

    if not parts:
        return {
            "available": False,
            "reason": "分位分量不足（需先刷新并补东财炸板/高度）",
            "s": None,
            "method": METHOD_PCT,
            "components": detail,
        }
    s = round(sum(parts) / len(parts), 2)
    return {
        "available": True,
        "s": s,
        "method": METHOD_PCT,
        "components": detail,
        "sample_days": len(rows),
        "used_components": len(parts),
    }


def _score_qcj_degree(date: str, rows: list[dict]) -> dict[str, Any]:
    for r in rows:
        if r.get("date") == date and r.get("qcj_temp") is not None:
            return {
                "available": True,
                "s": round(float(r["qcj_temp"]), 2),
                "method": METHOD_QCJ,
                "sample_days": len(rows),
            }
    # 序列未命中时现场打趣财经单日
    try:
        from . import short_board as sb

        zt = sb.zt_dt_for(date)
        # zt_dt_for 不返回 temp；读归档
        arch = sb._load_archive(date)
        if arch.get("qcj_temp") is not None:
            return {
                "available": True,
                "s": round(float(arch["qcj_temp"]), 2),
                "method": METHOD_QCJ,
                "source": "short_board_archive",
            }
        _ = zt
    except Exception:  # noqa: BLE001
        pass
    return {
        "available": False,
        "reason": f"无 {date} 的趣财经情绪分°",
        "s": None,
        "method": METHOD_QCJ,
    }


def score_for(date: str, *, method: Optional[str] = None) -> dict[str, Any]:
    """计算某场次 S。method 默认读配置。"""
    method = method or get_method()
    if method not in METHODS:
        method = METHOD_HARD
    if method == METHOD_HARD:
        return {
            "available": False,
            "reason": "当前算法为硬规则，不计算 S",
            "s": None,
            "method": METHOD_HARD,
        }

    rows = _load_series().get("rows") or []
    if not rows:
        try:
            refresh_series(enrich_limit=0)  # 先只拉趣财经，不堵在东财
            rows = _load_series().get("rows") or []
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "reason": f"拉取趣财经序列失败：{type(exc).__name__}: {exc}",
                "s": None,
                "method": method,
            }

    if method == METHOD_QCJ:
        return _score_qcj_degree(date, rows)
    if method == METHOD_PCT:
        # 目标日缺东财分量时补一天
        by = {r["date"]: r for r in rows}
        row = by.get(date)
        if row and (not row.get("em_ok") or row.get("highest") is None):
            patch = _enrich_one(date)
            row = {**row, **patch}
            by[date] = row
            rows = sorted(by.values(), key=lambda r: r["date"])
            _save_series(rows)
        return _score_percentile(date, rows)
    return {
        "available": False,
        "reason": f"未知算法 {method}",
        "s": None,
        "method": method,
    }


def classify_with_s(readings: dict, s: float) -> tuple[str, list[str]]:
    """有 S 时的定档：先防守叠加，再按 S 区间落档（永不自动「修复确认」）。"""
    from . import trade_budget as tb

    reasons: list[str] = []
    h = int(readings.get("highest") or 0)
    br = tb._f(readings.get("broken_rate")) or 0.0
    med = tb._f(readings.get("money_median"))
    p12 = tb._f(readings.get("promotion_1to2"))
    deep5 = tb._f(readings.get("deep_loss_5_rate"))
    mld = tb._f(readings.get("market_limit_down"))

    pressed = tb._height_pressed(readings)
    hurt = (
        br >= 0.40
        or (p12 is not None and p12 < 0.20)
        or (med is not None and med < 0)
        or (deep5 is not None and deep5 >= 0.25)
        or (mld is not None and mld >= 20)
    )
    if pressed and hurt:
        reasons.append(f"S={s}；高度压降且数据转差 → 退潮杀伤（叠加优先）")
        return "退潮杀伤", reasons

    if tb._height_near_peak(readings) and br >= 0.40:
        reasons.append(f"S={s}；高度近窗高位且炸板率≥40% → 过热防守（叠加优先）")
        return "过热防守", reasons

    if s > 80:
        reasons.append(f"S={s} > 80 → 过热防守")
        return "过热防守", reasons
    if s >= 55:
        reasons.append(f"S={s} 在 55–80 → 高潮拥挤")
        return "高潮拥挤", reasons
    if s >= 20:
        reasons.append(f"S={s} 在 20–55 → 升温扩张")
        return "升温扩张", reasons
    reasons.append(f"S={s} < 20 → 冰点观察")
    return "冰点观察", reasons
