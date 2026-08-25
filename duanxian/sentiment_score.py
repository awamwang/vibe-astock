"""合成情绪分 S（0–100）—— 定档可选主输入。

算法界面可选，落盘 `~/.duanxian-agents/config/sentiment_s.json`。
分位序列落盘 `~/.duanxian-agents/cache/series.db`（SQLite，表 `sentiment_s`）。
旧版 `cache/sentiment_s/series.json` 首次读取时自动迁入。
`hard_rules`：不用 S，维持涨停生态硬规则树。
`qcj_degree`：趣财经 temperatureDegree 原样当 S。
`percentile_qcj_em`：趣财经 ~220 日序列 + 炸板率/最高板补齐后分位等权合成。
`fusionintel`：聚变智研 A 股宏观恐贪指数（需 API Key）。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from . import series_store as store
from .util import atomic_write_json, china_now

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "sentiment_s.json")
_SERIES_PATH = os.path.expanduser("~/.duanxian-agents/cache/sentiment_s/series.json")
_SERIES_NAME = store.SERIES_SENTIMENT
_XGB_BROKEN_PATH = os.path.expanduser(
    "~/.duanxian-agents/cache/xgb_broken_rate/series.json"
)
_FUSION_CACHE_PATH = os.path.expanduser(
    "~/.duanxian-agents/cache/sentiment_s/fusionintel.json"
)
_SCHEMA = 1
_LOCK = threading.Lock()
# 测试可改写为临时 db 路径
_DB_PATH: Optional[str] = None

METHOD_HARD = "hard_rules"
METHOD_QCJ = "qcj_degree"
METHOD_PCT = "percentile_qcj_em"
METHOD_FUSION = "fusionintel"

_FUSION_URL = (
    "https://api.fusionintel.net/v1/feargreed/a_stock_macro/shi_feargreedindex"
)
_FUSION_PERIOD = "90d"

METHODS: dict[str, dict[str, Any]] = {
    METHOD_HARD: {
        "label": "硬规则（无 S）",
        "desc": "仅用涨停生态判定树定档，不计算合成情绪分。当前默认。",
        "needs_api_key": False,
    },
    METHOD_QCJ: {
        "label": "趣财经情绪分°",
        "desc": "直接用趣财经 temperatureDegree（0–100）作为合成情绪分 S。",
        "needs_api_key": False,
    },
    METHOD_PCT: {
        "label": "历史分位",
        "desc": "涨停/跌停/最高板/炸板率/情绪温度等历史分位等权合成 0–100。",
        "needs_api_key": False,
    },
    METHOD_FUSION: {
        "label": "FusionIntel 恐贪",
        "desc": "聚变智研 A 股宏观恐贪指数（0–100）原样当 S；须填写并保存 API Key。",
        "needs_api_key": True,
    },
}

# 分位合成用的分量：越高越热；invert=True 表示原始值越大越冷
_PCT_FIELDS = (
    ("limit_up", False),
    ("limit_down", True),
    ("highest", False),
    ("broken_rate", True),
    ("qcj_temp", False),
    ("margin_chg", False),  # 融资余额日变化（百分点）；缺历史时该分量自动跳过
    ("amount_vs_ma20", False),  # 两市成交额 / 20 日均（>1 偏放量）
)

_DEFAULT = {"schema": _SCHEMA, "method": METHOD_HARD, "fusionintel_api_key": ""}


class SentimentScoreError(ValueError):
    """情绪分配置非法。"""


def _mask_api_key(key: str) -> str:
    key = str(key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


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
        key = str(env.get("fusionintel_api_key") or "").strip()
        return {
            "schema": _SCHEMA,
            "method": method,
            "fusionintel_api_key": key,
        }
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT)


def get_method() -> str:
    return str(_read_config().get("method") or METHOD_HARD)


def get_fusionintel_api_key() -> str:
    return str(_read_config().get("fusionintel_api_key") or "").strip()


def set_method(method: str, *, fusionintel_api_key: Optional[str] = None) -> dict:
    """保存算法；选 FusionIntel 时须已有或本次传入非空 API Key。

    `fusionintel_api_key`：
    - None：不改动已存 Key
    - 非空字符串：覆盖写入
    - 空字符串：清空已存 Key（若同时选 FusionIntel 会报错）
    """
    method = str(method or "").strip()
    if method not in METHODS:
        raise SentimentScoreError(f"未知算法 {method!r}，只能是 {tuple(METHODS)}")

    prev = _read_config()
    if fusionintel_api_key is None:
        key = str(prev.get("fusionintel_api_key") or "").strip()
    else:
        key = str(fusionintel_api_key).strip()

    if method == METHOD_FUSION and not key:
        raise SentimentScoreError(
            "选择 FusionIntel 须填写 API Key（可在 https://fusionintel.net/ 注册获取）"
        )

    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {
        "schema": _SCHEMA,
        "method": method,
        "fusionintel_api_key": key,
    }
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入情绪分配置失败：{_CONFIG_PATH}")
    return export_config()


def export_config() -> dict[str, Any]:
    from . import market_series as ms

    cfg = _read_config()
    key = str(cfg.get("fusionintel_api_key") or "").strip()
    st = ms.series_status()
    return {
        "schema": _SCHEMA,
        "path": _CONFIG_PATH,
        "method": cfg["method"],
        "methods": [
            {
                "id": mid,
                "label": meta["label"],
                "desc": meta["desc"],
                "needs_api_key": bool(meta.get("needs_api_key")),
            }
            for mid, meta in METHODS.items()
        ],
        "series_path": _DB_PATH or store.DB_PATH,
        "series_legacy_path": _SERIES_PATH,
        "series_meta": series_meta(),
        "market_series": {
            "margin": st.get("margin"),
            "index": st.get("index"),
            "needs_refresh": ms.needs_refresh(),
        },
        "has_fusionintel_api_key": bool(key),
        "fusionintel_api_key_masked": _mask_api_key(key),
    }


def series_meta() -> dict[str, Any]:
    env = _load_series()
    rows = env.get("rows") or []
    enriched = sum(1 for r in rows if r.get("em_ok"))
    missed = sum(1 for r in rows if r.get("em_miss") and not r.get("em_ok"))
    pending = sum(1 for r in rows if _needs_em_enrich(r))
    highest_n = sum(1 for r in rows if r.get("highest") is not None)
    broken_n = sum(1 for r in rows if r.get("broken_rate") is not None)
    return {
        "days": len(rows),
        "enriched_days": enriched,
        "miss_days": missed,
        "pending_days": pending,
        "highest_days": highest_n,
        "broken_rate_days": broken_n,
        "first": rows[0]["date"] if rows else None,
        "last": rows[-1]["date"] if rows else None,
        "updated_at": env.get("updated_at"),
    }


def _load_series() -> dict:
    store.migrate_json_file(_SERIES_NAME, _SERIES_PATH, path=_DB_PATH)
    return store.load_envelope(_SERIES_NAME, path=_DB_PATH)


def _save_series(rows: list[dict]) -> dict:
    return store.replace_rows(_SERIES_NAME, rows, source="sentiment_score", path=_DB_PATH)


def _parse_leader_day_top(text: Any) -> Optional[int]:
    """趣财经 leaderDayTop（如『5天5板』『16天8板』）→ 板高。

    取末尾「N板」；与东财涨停池 max(连板数) 多数日一致，偶有偏差，
    仅作东财窗口外的一次性落盘回补。
    """
    import re

    if text is None:
        return None
    m = re.search(r"(\d+)\s*板", str(text).strip())
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if n > 0 else None


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
        leader_top = str(row.get("leaderDayTop") or "").strip() or None
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
            "consec_boards": consec_n,  # 连板家数（非最高板）
            "leader_top": leader_top,
            "qcj_highest": _parse_leader_day_top(leader_top),
            "level": str(row.get("sentimentLevel") or "") or None,
        })
    out.sort(key=lambda r: r["date"])
    return out


def _backfill_highest_from_qcj(by_date: dict[str, dict]) -> int:
    """东财未覆盖日：用趣财经龙头高度一次性补 highest（落盘后不再依赖外网池）。"""
    filled = 0
    for item in by_date.values():
        if item.get("highest") is not None:
            continue
        h = item.get("qcj_highest")
        if h is None:
            h = _parse_leader_day_top(item.get("leader_top"))
        if h is None:
            continue
        item["highest"] = int(h)
        item["highest_source"] = "qcj_leader"
        filled += 1
    return filled


def _xgb_broken_map() -> dict[str, float]:
    """选股宝离线炸板率：date → ratio（0–1）。文件不存在或损坏时返回空表。"""
    if not os.path.isfile(_XGB_BROKEN_PATH):
        return {}
    try:
        with open(_XGB_BROKEN_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    rows = raw.get("rows") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("ok"):
            continue
        d = row.get("date")
        br = row.get("broken_rate")
        if not d or br is None:
            continue
        try:
            out[str(d)] = float(br)
        except (TypeError, ValueError):
            continue
    return out


def _apply_xgb_broken(by_date: dict[str, dict]) -> int:
    """用选股宝炸板率覆盖分位序列（优先口径；覆盖近窗东财同字段）。"""
    mapping = _xgb_broken_map()
    if not mapping:
        return 0
    filled = 0
    for d, item in by_date.items():
        br = mapping.get(d)
        if br is None:
            continue
        item["broken_rate"] = br
        item["broken_rate_source"] = "xgb"
        filled += 1
    return filled


def _enrich_one(date: str) -> dict[str, Any]:
    """近窗补最高连板（兼可得炸板率兜底）。优先本机 AKTools，再回退本地 akshare。"""
    from . import market_series as ms

    via = ms.zt_summary_via_aktools(date)
    if via and via.get("em_ok") and (
        via.get("highest") is not None or via.get("broken_rate") is not None
    ):
        return {
            "highest": via.get("highest"),
            "broken_rate": via.get("broken_rate"),
            "em_ok": True,
        }

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


def _needs_em_enrich(item: dict) -> bool:
    """是否还缺最高板；已标记 em_miss 的不再重试。炸板率改由选股宝序列覆盖。"""
    if item.get("em_miss") and not item.get("em_ok"):
        return False
    return item.get("highest") is None


def refresh_series(*, enrich_limit: Optional[int] = None) -> dict[str, Any]:
    """回拉趣财经序列；炸板率并入选股宝离线序列，近窗按需补最高板；结果落盘。

    `enrich_limit`：本轮最多尝试几天近窗高度补齐（None=缺什么补什么）。
    从**最近交易日往旧**补高度；拉取失败的日期打 `em_miss`，后续轮次跳过。
    """
    from . import market_series as ms

    market_refresh: dict[str, Any] = {"ok": False, "skipped": True}
    try:
        market_refresh = ms.ensure_fresh()
    except Exception as exc:  # noqa: BLE001
        market_refresh = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    with _LOCK:
        qcj = _fetch_qcj_rows()
        if not qcj:
            raise RuntimeError("趣财经情绪序列为空")
        margin_by = ms.margin_map()
        amount_by = ms.amount_metrics_map()
        old = {r["date"]: r for r in (_load_series().get("rows") or []) if r.get("date")}
        by_date: dict[str, dict] = {}
        for row in qcj:
            d = row["date"]
            prev = old.get(d) or {}
            mrow = margin_by.get(d) or {}
            amrow = amount_by.get(d) or {}
            by_date[d] = {
                **row,
                "highest": prev.get("highest"),
                "broken_rate": prev.get("broken_rate"),
                "broken_rate_source": prev.get("broken_rate_source"),
                "em_ok": bool(prev.get("em_ok")),
                "em_miss": bool(prev.get("em_miss")) and not bool(prev.get("em_ok")),
                "highest_source": prev.get("highest_source"),
                "margin_chg": mrow.get("margin_chg", prev.get("margin_chg")),
                "amount_yi": amrow.get("amount_yi", prev.get("amount_yi")),
                "amount_vs_ma20": amrow.get("amount_vs_ma20", prev.get("amount_vs_ma20")),
            }

        # 炸板率优先并入选股宝离线口径（覆盖旧东财近窗值）
        xgb_filled = _apply_xgb_broken(by_date)

        # 近窗日期清掉 miss，允许重试（盘中/当日池可能稍后才齐）
        recent = sorted(by_date.keys())[-5:]
        for d in recent:
            if by_date[d].get("em_miss") and not by_date[d].get("em_ok"):
                by_date[d]["em_miss"] = False

        candidates = sorted(
            (d for d, item in by_date.items() if _needs_em_enrich(item)),
            reverse=True,
        )
        if enrich_limit is not None:
            candidates = candidates[: max(0, int(enrich_limit))]

        enriched_ok = 0
        missed = 0
        for d in candidates:
            item = by_date[d]
            keep_br = item.get("broken_rate")
            keep_br_src = item.get("broken_rate_source")
            patch = _enrich_one(d)
            if patch.get("highest") is not None:
                item["highest"] = patch["highest"]
                item["highest_source"] = "em"
            # 已有选股宝炸板率则保留；否则近窗兜底
            if keep_br_src == "xgb" and keep_br is not None:
                item["broken_rate"] = keep_br
                item["broken_rate_source"] = "xgb"
            elif patch.get("broken_rate") is not None:
                item["broken_rate"] = patch["broken_rate"]
                item["broken_rate_source"] = "em"
            item["em_ok"] = bool(patch.get("em_ok")) and item.get("highest") is not None
            if item["em_ok"]:
                item["em_miss"] = False
                enriched_ok += 1
            else:
                item["em_ok"] = False
                item["em_miss"] = True
                missed += 1

        # 近窗高度大致连续：本轮已有成功日时，更早的未补日直接记 miss，免反复空打
        if enriched_ok > 0:
            oldest_ok = min(
                d for d, item in by_date.items()
                if item.get("em_ok") and item.get("highest") is not None
            )
            for d, item in by_date.items():
                if d < oldest_ok and _needs_em_enrich(item):
                    item["em_ok"] = False
                    item["em_miss"] = True

        # 近窗补不了更早：用趣财经龙头高度一次性回补 highest 并落盘
        qcj_filled = _backfill_highest_from_qcj(by_date)
        # 再并一次，避免高度回补路径覆盖炸板率字段
        xgb_filled = _apply_xgb_broken(by_date)

        merged = [by_date[r["date"]] for r in qcj]
        env = _save_series(merged)
        return {
            "ok": True,
            "enriched_this_run": enriched_ok,
            "missed_this_run": missed,
            "tried_this_run": enriched_ok + missed,
            "qcj_highest_filled": qcj_filled,
            "xgb_broken_filled": xgb_filled,
            "meta": series_meta(),
            "updated_at": env.get("updated_at"),
            "margin_joined": sum(1 for r in merged if r.get("margin_chg") is not None),
            "market_refresh": market_refresh,
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
        "margin_chg": None if row.get("margin_chg") is None else float(row["margin_chg"]),
        "amount_vs_ma20": None if row.get("amount_vs_ma20") is None else float(row["amount_vs_ma20"]),
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


def _load_fusion_cache() -> dict:
    if not os.path.isfile(_FUSION_CACHE_PATH):
        return {"schema": _SCHEMA, "rows": [], "updated_at": None, "period": None}
    try:
        with open(_FUSION_CACHE_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if isinstance(env, dict) and isinstance(env.get("rows"), list):
            return env
    except Exception:  # noqa: BLE001
        pass
    return {"schema": _SCHEMA, "rows": [], "updated_at": None, "period": None}


def _save_fusion_cache(rows: list[dict], *, period: str) -> dict:
    os.makedirs(os.path.dirname(_FUSION_CACHE_PATH), exist_ok=True)
    env = {
        "schema": _SCHEMA,
        "period": period,
        "rows": rows,
        "updated_at": china_now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_day": china_now().strftime("%Y-%m-%d"),
    }
    atomic_write_json(_FUSION_CACHE_PATH, env)
    return env


def _parse_fusion_rows(payload: Any) -> list[dict]:
    """解析 FusionIntel 响应为 [{date, s, price}, ...]。"""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        date_s: Optional[str] = None
        s_val: Optional[float] = None
        price: Optional[float] = None
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            date_s = str(item[0] or "").strip()[:10]
            try:
                price = None if item[1] is None else float(item[1])
            except (TypeError, ValueError):
                price = None
            try:
                s_val = None if item[2] is None else float(item[2])
            except (TypeError, ValueError):
                s_val = None
        elif isinstance(item, dict):
            date_s = str(item.get("date") or "").strip()[:10]
            try:
                s_val = float(item.get("feargreed_index", item.get("s")))
            except (TypeError, ValueError):
                s_val = None
            try:
                p = item.get("price")
                price = None if p is None else float(p)
            except (TypeError, ValueError):
                price = None
        if not date_s or s_val is None:
            continue
        out.append({"date": date_s, "s": round(s_val, 2), "price": price})
    out.sort(key=lambda r: r["date"])
    return out


def _fetch_fusionintel(api_key: str, *, period: str = _FUSION_PERIOD) -> list[dict]:
    import requests

    r = requests.get(
        _FUSION_URL,
        params={"period": period},
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "vibe-astock-sentiment-s/1.0",
        },
        timeout=20,
    )
    if r.status_code in (401, 403):
        raise SentimentScoreError("FusionIntel API Key 无效或无权限")
    r.raise_for_status()
    rows = _parse_fusion_rows(r.json())
    if not rows:
        raise RuntimeError("FusionIntel 返回空序列")
    return rows


def _fusion_rows_for_score(api_key: str) -> list[dict]:
    """当日已拉过则用缓存，否则请求并落盘。"""
    with _LOCK:
        cache = _load_fusion_cache()
        today = china_now().strftime("%Y-%m-%d")
        rows = cache.get("rows") or []
        if rows and cache.get("updated_day") == today:
            return rows
        rows = _fetch_fusionintel(api_key)
        _save_fusion_cache(rows, period=_FUSION_PERIOD)
        return rows


def _score_fusionintel(date: str) -> dict[str, Any]:
    api_key = get_fusionintel_api_key()
    if not api_key:
        return {
            "available": False,
            "reason": "未配置 FusionIntel API Key（设置页选择该算法并保存 Key）",
            "s": None,
            "method": METHOD_FUSION,
        }
    try:
        rows = _fusion_rows_for_score(api_key)
    except SentimentScoreError as exc:
        return {
            "available": False,
            "reason": str(exc),
            "s": None,
            "method": METHOD_FUSION,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"拉取 FusionIntel 失败：{type(exc).__name__}: {exc}",
            "s": None,
            "method": METHOD_FUSION,
        }

    exact = next((r for r in rows if r.get("date") == date), None)
    if exact is not None:
        return {
            "available": True,
            "s": float(exact["s"]),
            "method": METHOD_FUSION,
            "source": "fusionintel",
            "data_date": date,
            "sample_days": len(rows),
        }
    # 取不超过目标日的最近一日（节假日 / 延迟更新）
    prior = [r for r in rows if str(r.get("date") or "") <= date]
    if prior:
        hit = prior[-1]
        return {
            "available": True,
            "s": float(hit["s"]),
            "method": METHOD_FUSION,
            "source": "fusionintel",
            "data_date": hit["date"],
            "sample_days": len(rows),
            "note": f"无 {date}，沿用 {hit['date']}",
        }
    return {
        "available": False,
        "reason": f"FusionIntel 序列中无 ≤ {date} 的数据",
        "s": None,
        "method": METHOD_FUSION,
        "sample_days": len(rows),
    }


# 东财涨停池近窗量级；定档自动补齐时每轮上限，避免窗外空打拖慢
_AUTO_EM_ENRICH_LIMIT = 16


def _pct_needs_auto_refresh(date: str, rows: list[dict]) -> bool:
    """历史分位定档前：序列空、缺目标日、或近窗仍缺东财时需要自动刷新。"""
    if not rows:
        return True
    by = {r["date"]: r for r in rows if r.get("date")}
    if date not in by:
        return True
    recent = sorted(by.keys())[-_AUTO_EM_ENRICH_LIMIT:]
    return any(_needs_em_enrich(by[d]) for d in recent)


def _merge_market_into_rows(rows: list[dict]) -> list[dict]:
    """把已刷新的两融/成交额并回分位行，免整段重拉趣财经。"""
    from . import market_series as ms

    margin_by = ms.margin_map()
    amount_by = ms.amount_metrics_map()
    changed = False
    out: list[dict] = []
    for r in rows:
        item = dict(r)
        d = item.get("date")
        if d:
            mrow = margin_by.get(d) or {}
            amrow = amount_by.get(d) or {}
            if item.get("margin_chg") is None and mrow.get("margin_chg") is not None:
                item["margin_chg"] = mrow["margin_chg"]
                changed = True
            if item.get("amount_vs_ma20") is None and amrow.get("amount_vs_ma20") is not None:
                item["amount_yi"] = amrow.get("amount_yi", item.get("amount_yi"))
                item["amount_vs_ma20"] = amrow["amount_vs_ma20"]
                changed = True
        out.append(item)
    if changed:
        _save_series(out)
        return list(_load_series().get("rows") or [])
    return out


def _patch_target_day_em(date: str, rows: list[dict]) -> list[dict]:
    """目标日缺高度时：先落盘趣财经龙头高度，再按需打近窗池；炸板率优先选股宝。"""
    by = {r["date"]: r for r in rows if r.get("date")}
    row = by.get(date)
    if not row:
        return rows
    changed = False
    xgb = _xgb_broken_map()
    if date in xgb and (
        row.get("broken_rate") is None or row.get("broken_rate_source") != "xgb"
    ):
        row = {
            **row,
            "broken_rate": xgb[date],
            "broken_rate_source": "xgb",
        }
        changed = True
    if row.get("em_ok") and row.get("highest") is not None:
        if changed:
            by[date] = row
            merged = sorted(by.values(), key=lambda r: r["date"])
            _save_series(merged)
            return merged
        return rows
    if row.get("highest") is None:
        h = row.get("qcj_highest")
        if h is None:
            h = _parse_leader_day_top(row.get("leader_top"))
        if h is not None:
            row = {
                **row,
                "highest": int(h),
                "highest_source": row.get("highest_source") or "qcj_leader",
            }
            changed = True
    if not row.get("em_ok") and not row.get("em_miss"):
        patch = _enrich_one(date)
        keep_br = row.get("broken_rate")
        keep_src = row.get("broken_rate_source")
        if patch.get("em_ok") and patch.get("highest") is not None:
            row = {
                **row,
                "highest": patch["highest"],
                "em_ok": True,
                "em_miss": False,
                "highest_source": "em",
                "broken_rate": (
                    keep_br
                    if keep_src == "xgb" and keep_br is not None
                    else (
                        patch["broken_rate"]
                        if patch.get("broken_rate") is not None
                        else keep_br
                    )
                ),
                "broken_rate_source": (
                    "xgb"
                    if keep_src == "xgb" and keep_br is not None
                    else (
                        "em"
                        if patch.get("broken_rate") is not None
                        else keep_src
                    )
                ),
            }
        else:
            row = {**row, "em_miss": True}
        changed = True
    if not changed:
        return rows
    by[date] = row
    merged = sorted(by.values(), key=lambda r: r["date"])
    _save_series(merged)
    return merged


def _ensure_percentile_for_score(date: str) -> list[dict]:
    """六档定档用历史分位时自动补齐：市场序列 + 近窗东财/趣财经。"""
    from . import market_series as ms

    try:
        ms.ensure_fresh()
    except Exception:  # noqa: BLE001
        pass

    rows = list(_load_series().get("rows") or [])
    if _pct_needs_auto_refresh(date, rows):
        try:
            refresh_series(enrich_limit=_AUTO_EM_ENRICH_LIMIT)
            rows = list(_load_series().get("rows") or [])
        except Exception:  # noqa: BLE001
            pass
    elif rows:
        try:
            rows = _merge_market_into_rows(rows)
        except Exception:  # noqa: BLE001
            pass

    if rows:
        rows = _patch_target_day_em(date, rows)
    return rows


def score_for(date: str, *, method: Optional[str] = None) -> dict[str, Any]:
    """计算某场次 S。method 默认读配置。

    历史分位（percentile_qcj_em）在定档路径会自动补齐近窗东财与市场序列。
    """
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
    if method == METHOD_FUSION:
        return _score_fusionintel(date)

    if method == METHOD_PCT:
        rows = _ensure_percentile_for_score(date)
        if not rows:
            return {
                "available": False,
                "reason": "拉取分位序列失败（请检查趣财经/网络）",
                "s": None,
                "method": method,
            }
        return _score_percentile(date, rows)

    rows = _load_series().get("rows") or []
    if not rows:
        try:
            refresh_series(enrich_limit=0)  # 趣财经°只需序列，不堵在东财
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
    return {
        "available": False,
        "reason": f"未知算法 {method}",
        "s": None,
        "method": method,
    }


def classify_with_s(readings: dict, s: float) -> tuple[str, list[str]]:
    """有 S 时的定档：先防守叠加，再按 S 区间落档（永不自动「修复确认」）。"""
    from . import trade_budget as tb
    from . import trade_threshold_config as ttc

    th = ttc.resolved()
    reasons: list[str] = []
    br = tb._f(readings.get("broken_rate")) or 0.0
    med = tb._f(readings.get("money_median"))
    p12 = tb._f(readings.get("promotion_1to2"))
    deep5 = tb._f(readings.get("deep_loss_5_rate"))
    mld = tb._f(readings.get("market_limit_down"))

    pressed = tb._height_pressed(readings)
    hurt = (
        br >= th["broken_rate_ge"]
        or (p12 is not None and p12 < th["promo_hurt_lt"])
        or (med is not None and med < th["money_hurt_lt"])
        or (deep5 is not None and deep5 >= th["deep_loss_ge"])
        or (mld is not None and mld >= th["limit_down_ge"])
    )
    if pressed and hurt:
        reasons.append(f"S={s}；高度压降且数据转差 → 退潮杀伤（叠加优先）")
        return "退潮杀伤", reasons

    if tb._height_near_peak(readings) and br >= th["broken_rate_ge"]:
        reasons.append(
            f"S={s}；高度近窗高位且炸板率≥{th['broken_rate_ge'] * 100:.0f}% → 过热防守（叠加优先）"
        )
        return "过热防守", reasons

    if s > th["s_overheat_gt"]:
        reasons.append(f"S={s} > {th['s_overheat_gt']:g} → 过热防守")
        return "过热防守", reasons
    if s >= th["s_climax_ge"]:
        reasons.append(
            f"S={s} 在 {th['s_climax_ge']:g}–{th['s_overheat_gt']:g} → 高潮拥挤"
        )
        return "高潮拥挤", reasons
    if s >= th["s_warm_ge"]:
        reasons.append(
            f"S={s} 在 {th['s_warm_ge']:g}–{th['s_climax_ge']:g} → 升温扩张"
        )
        return "升温扩张", reasons
    reasons.append(f"S={s} < {th['s_ice_lt']:g} → 冰点观察")
    return "冰点观察", reasons
