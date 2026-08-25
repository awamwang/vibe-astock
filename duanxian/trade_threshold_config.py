"""定档阈值（硬规则 + S 区间）—— 可落盘覆盖。

配置落盘：`~/.duanxian-agents/config/trade_thresholds.json`
未改字段沿用内置默认（与原先写死在 classify 里的数字一致）。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from .util import atomic_write_json

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "trade_thresholds.json")
_SCHEMA = 1
_LOCK = threading.Lock()
_CACHE: Optional[dict[str, float]] = None

# value_kind: ratio=0–1；number=可正负；count=家数；boards=板数；score=0–100
# ref_key 对齐 risk_stance.gather_readings / trade_budget.classify_rule_phase
_FIELD_META: list[dict[str, Any]] = [
    {
        "key": "broken_rate_ge",
        "group": "hard_rules",
        "label": "炸板率下限",
        "desc": "过热防守主条件；退潮「数据转差」五选一。炸板率 ≥ 此值视为偏热/转差。",
        "value_kind": "ratio",
        "ref_key": "broken_rate",
        "default": 0.40,
        "min": 0.0,
        "max": 1.0,
    },
    {
        "key": "promo_hurt_lt",
        "group": "hard_rules",
        "label": "转差·1进2 上限",
        "desc": "退潮「数据转差」：1进2 晋级率 < 此值算转差。",
        "value_kind": "ratio",
        "ref_key": "promotion_1to2",
        "default": 0.20,
        "min": 0.0,
        "max": 1.0,
    },
    {
        "key": "money_hurt_lt",
        "group": "hard_rules",
        "label": "转差/冰点·赚钱中位",
        "desc": "赚钱效应中位 < 此值：计入退潮转差，也计入冰点条件之一。",
        "value_kind": "number",
        "ref_key": "money_median",
        "default": 0.0,
        "min": -50.0,
        "max": 50.0,
    },
    {
        "key": "deep_loss_ge",
        "group": "hard_rules",
        "label": "转差·深亏占比",
        "desc": "深亏占比 ≥ 此值 → 退潮转差。",
        "value_kind": "ratio",
        "ref_key": "deep_loss_5_rate",
        "default": 0.25,
        "min": 0.0,
        "max": 1.0,
    },
    {
        "key": "limit_down_ge",
        "group": "hard_rules",
        "label": "转差·跌停家数",
        "desc": "跌停家数 ≥ 此值 → 退潮转差。",
        "value_kind": "count",
        "ref_key": "market_limit_down",
        "default": 20.0,
        "min": 0.0,
        "max": 500.0,
    },
    {
        "key": "climax_highest_ge",
        "group": "hard_rules",
        "label": "高潮·最高连板",
        "desc": "最高连板 ≥ 此值，且赚钱中位达标 → 高潮拥挤。",
        "value_kind": "boards",
        "ref_key": "highest",
        "default": 5.0,
        "min": 1.0,
        "max": 20.0,
    },
    {
        "key": "money_climax_ge",
        "group": "hard_rules",
        "label": "高潮·赚钱中位下限",
        "desc": "高潮拥挤还要求赚钱效应中位 ≥ 此值。",
        "value_kind": "number",
        "ref_key": "money_median",
        "default": 0.0,
        "min": -50.0,
        "max": 50.0,
    },
    {
        "key": "ice_highest_le",
        "group": "hard_rules",
        "label": "冰点·最高连板上限",
        "desc": "最高连板 ≤ 此值，且（赚钱差 / 晋级弱 / 涨停稀）任一成立 → 冰点观察。",
        "value_kind": "boards",
        "ref_key": "highest",
        "default": 3.0,
        "min": 1.0,
        "max": 20.0,
    },
    {
        "key": "ice_promo_lt",
        "group": "hard_rules",
        "label": "冰点·1进2 上限",
        "desc": "冰点条件之一：1进2 < 此值（通常严于或等于「转差」阈值）。",
        "value_kind": "ratio",
        "ref_key": "promotion_1to2",
        "default": 0.15,
        "min": 0.0,
        "max": 1.0,
    },
    {
        "key": "ice_limit_up_lt",
        "group": "hard_rules",
        "label": "冰点·涨停家数上限",
        "desc": "冰点条件之一：涨停家数 < 此值。",
        "value_kind": "count",
        "ref_key": "limit_up",
        "default": 30.0,
        "min": 0.0,
        "max": 500.0,
    },
    {
        "key": "height_press_gap",
        "group": "hard_rules",
        "label": "高度压降·回落板数",
        "desc": "近窗峰值 ≥ 当前高度 + 此值，才算高度压降（退潮必要条件）。",
        "value_kind": "boards",
        "ref_key": "highest",
        "default": 1.0,
        "min": 1.0,
        "max": 10.0,
    },
    {
        "key": "height_press_peak_min",
        "group": "hard_rules",
        "label": "高度压降·峰值下限",
        "desc": "近窗峰值还须 ≥ 此值，避免低位抖动误判压降。",
        "value_kind": "boards",
        "ref_key": "highest_hist_peak",
        "default": 4.0,
        "min": 1.0,
        "max": 20.0,
    },
    {
        "key": "height_near_min",
        "group": "hard_rules",
        "label": "近窗高位·高度下限",
        "desc": "有历史窗时：当前高度 ≥ 近窗峰值 且 ≥ 此值 → 近窗高位（过热用）。",
        "value_kind": "boards",
        "ref_key": "highest",
        "default": 4.0,
        "min": 1.0,
        "max": 20.0,
    },
    {
        "key": "height_near_no_hist",
        "group": "hard_rules",
        "label": "近窗高位·无历史退化",
        "desc": "没有近窗历史时，当前高度 ≥ 此值即视为近窗高位。",
        "value_kind": "boards",
        "ref_key": "highest",
        "default": 5.0,
        "min": 1.0,
        "max": 20.0,
    },
    {
        "key": "s_ice_lt",
        "group": "s_bands",
        "label": "S·冰点上界",
        "desc": "S < 此值 → 冰点观察（叠加退潮/过热仍优先）。",
        "value_kind": "score",
        "ref_key": "s",
        "default": 20.0,
        "min": 0.0,
        "max": 100.0,
    },
    {
        "key": "s_warm_ge",
        "group": "s_bands",
        "label": "S·升温下界",
        "desc": "S ≥ 此值且 < 高潮下界 → 升温扩张。通常与冰点上界相同。",
        "value_kind": "score",
        "ref_key": "s",
        "default": 20.0,
        "min": 0.0,
        "max": 100.0,
    },
    {
        "key": "s_climax_ge",
        "group": "s_bands",
        "label": "S·高潮下界",
        "desc": "S ≥ 此值且 ≤ 过热上界 → 高潮拥挤。",
        "value_kind": "score",
        "ref_key": "s",
        "default": 55.0,
        "min": 0.0,
        "max": 100.0,
    },
    {
        "key": "s_overheat_gt",
        "group": "s_bands",
        "label": "S·过热下界",
        "desc": "S > 此值 → 过热防守。",
        "value_kind": "score",
        "ref_key": "s",
        "default": 80.0,
        "min": 0.0,
        "max": 100.0,
    },
]

_GROUPS = [
    {
        "id": "hard_rules",
        "label": "一、硬规则定档",
        "desc": "无合成情绪分 S、或算法为硬规则树时使用。退潮/过热叠加在有 S 时仍优先。",
    },
    {
        "id": "s_bands",
        "label": "二、S 区间定档",
        "desc": "选用趣财经温度 / 分位合成等算法时，在叠加规则之后按 S 落档。",
    },
]

_DEFAULTS: dict[str, float] = {f["key"]: float(f["default"]) for f in _FIELD_META}
_META_BY_KEY: dict[str, dict[str, Any]] = {f["key"]: f for f in _FIELD_META}


class TradeThresholdConfigError(ValueError):
    """定档阈值配置非法。"""


def default_values() -> dict[str, float]:
    return dict(_DEFAULTS)


def _as_number(v: object, meta: dict[str, Any]) -> float:
    label = meta["label"]
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise TradeThresholdConfigError(f"{label} 须为数字") from exc
    if x != x or abs(x) == float("inf"):  # noqa: PLR0124
        raise TradeThresholdConfigError(f"{label} 须为有限数字")
    lo, hi = float(meta["min"]), float(meta["max"])
    if x < lo or x > hi:
        raise TradeThresholdConfigError(f"{label} 须在 {lo}–{hi}")
    kind = meta["value_kind"]
    if kind in ("boards", "count"):
        return float(int(round(x)))
    if kind == "score":
        return round(x, 2)
    if kind == "ratio":
        return round(x, 4)
    return round(x, 4)


def _overlay_from_raw(raw: object, *, strict: bool) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise TradeThresholdConfigError("thresholds 须为对象")
        return {}
    out: dict[str, float] = {}
    for key, val in raw.items():
        k = str(key).strip()
        meta = _META_BY_KEY.get(k)
        if meta is None:
            if strict:
                raise TradeThresholdConfigError(f"未知阈值 {k!r}")
            continue
        if val is None:
            continue
        try:
            out[k] = _as_number(val, meta)
        except TradeThresholdConfigError:
            if strict:
                raise
    return out


def _validate_bands(values: dict[str, float]) -> None:
    ice = values["s_ice_lt"]
    warm = values["s_warm_ge"]
    climax = values["s_climax_ge"]
    overheat = values["s_overheat_gt"]
    if warm < ice:
        raise TradeThresholdConfigError("S·升温下界不能小于 S·冰点上界")
    if climax <= warm:
        raise TradeThresholdConfigError("S·高潮下界须大于 S·升温下界")
    if overheat < climax:
        raise TradeThresholdConfigError("S·过热下界不能小于 S·高潮下界")
    if values["ice_promo_lt"] > values["promo_hurt_lt"] + 1e-12:
        raise TradeThresholdConfigError("冰点·1进2 上限不应大于 转差·1进2 上限（冰点应更严或持平）")


def _read_overlay() -> dict[str, float]:
    if not os.path.isfile(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return {}
        return _overlay_from_raw(env.get("thresholds"), strict=False)
    except Exception:  # noqa: BLE001
        return {}


def load_overlay() -> dict[str, float]:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    with _LOCK:
        if _CACHE is None:
            _CACHE = _read_overlay()
        return dict(_CACHE)


def reload_overlay() -> dict[str, float]:
    global _CACHE
    with _LOCK:
        _CACHE = _read_overlay()
        return dict(_CACHE)


def resolved() -> dict[str, float]:
    out = default_values()
    out.update(load_overlay())
    return out


def get(key: str) -> float:
    if key not in _META_BY_KEY:
        raise KeyError(key)
    return resolved()[key]


def save_values(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise TradeThresholdConfigError("thresholds 须为对象")
    merged = resolved()
    merged.update(_overlay_from_raw(raw, strict=True))
    _validate_bands(merged)
    overlay = {k: v for k, v in merged.items() if abs(v - _DEFAULTS[k]) > 1e-9}
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "thresholds": overlay}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入定档阈值失败：{_CONFIG_PATH}")
    global _CACHE
    with _LOCK:
        _CACHE = dict(overlay)
    return resolved()


def reset_values() -> dict[str, float]:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "thresholds": {}}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入定档阈值失败：{_CONFIG_PATH}")
    global _CACHE
    with _LOCK:
        _CACHE = {}
    return resolved()


def _fmt_ref(kind: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "ratio":
        return f"{x * 100:.1f}%"
    if kind in ("boards", "count"):
        return str(int(round(x)))
    if kind == "score":
        return f"{x:.1f}"
    return f"{x:.2f}"


def _readings_from_budget(date: str) -> Optional[dict[str, Any]]:
    """优先用已落盘预算里的 readings，避免设置页触发重型抓取。"""
    try:
        from . import trade_store as ts

        env = ts.load_day(date)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(env, dict):
        return None
    readings = env.get("readings")
    return readings if isinstance(readings, dict) else None


def _reference_pack() -> dict[str, Any]:
    from . import trade_calendar as tc

    date = tc.latest_session()
    if not date:
        return {"date": None, "readings": {}, "display": [], "reason": "尚无已收盘场次"}

    readings = _readings_from_budget(date)
    reason: Optional[str]
    if readings is None:
        try:
            from . import risk_stance as rs

            readings = rs.gather_readings(date)
            reason = "来自实时组装（当日尚无落盘预算）"
        except Exception as exc:  # noqa: BLE001
            return {
                "date": date,
                "readings": {},
                "display": [],
                "reason": f"读数不可用：{type(exc).__name__}: {exc}",
            }
    else:
        reason = "来自最近一场落盘预算"

    hist = readings.get("highest_hist") or []
    peak = max(hist) if isinstance(hist, list) and hist else None
    enriched = dict(readings)
    enriched["highest_hist_peak"] = peak

    display_specs = [
        ("limit_up", "涨停家数", "count"),
        ("broken_rate", "炸板率", "ratio"),
        ("highest", "最高连板", "boards"),
        ("highest_hist_peak", "近窗峰值", "boards"),
        ("money_median", "赚钱效应中位", "number"),
        ("promotion_1to2", "1进2 晋级率", "ratio"),
        ("deep_loss_5_rate", "深亏占比", "ratio"),
        ("market_limit_down", "跌停家数", "count"),
        ("s", "合成情绪分 S", "score"),
    ]
    display = []
    for key, label, kind in display_specs:
        raw = enriched.get(key)
        display.append({
            "key": key,
            "label": label,
            "value": raw,
            "formatted": _fmt_ref(kind, raw),
        })
    return {
        "date": date,
        "readings": {
            k: enriched.get(k)
            for k in (
                "limit_up",
                "broken_rate",
                "highest",
                "highest_hist",
                "highest_hist_peak",
                "money_median",
                "promotion_1to2",
                "deep_loss_5_rate",
                "market_limit_down",
                "s",
                "s_ok",
                "s_method",
            )
        },
        "display": display,
        "reason": reason,
    }


def export_config() -> dict[str, Any]:
    values = resolved()
    groups_out = []
    for g in _GROUPS:
        fields = []
        for meta in _FIELD_META:
            if meta["group"] != g["id"]:
                continue
            key = meta["key"]
            fields.append({
                "key": key,
                "label": meta["label"],
                "desc": meta["desc"],
                "value_kind": meta["value_kind"],
                "ref_key": meta["ref_key"],
                "value": values[key],
                "default": meta["default"],
                "min": meta["min"],
                "max": meta["max"],
            })
        groups_out.append({**g, "fields": fields})
    return {
        "schema": _SCHEMA,
        "path": _CONFIG_PATH,
        "groups": groups_out,
        "values": values,
        "defaults": default_values(),
        "reference": _reference_pack(),
    }
