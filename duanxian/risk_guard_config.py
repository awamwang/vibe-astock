"""账户风控闸软/硬阈值 —— 可落盘覆盖。

配置落盘：`{profile}/.duanxian-agents/config/risk_guard.json`
未改字段沿用内置默认。亏损持仓累积的并集窗口固定 3 个有快照交易日，不开放配置。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from . import paths as _paths
from .util import atomic_write_json

_CONFIG_DIR = ""
_CONFIG_PATH = ""
_SCHEMA = 1
_LOCK = threading.Lock()
_CACHE: Optional[dict[str, float]] = None

UNION_WINDOW_DAYS = 3


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "risk_guard.json")


class RiskGuardConfigError(ValueError):
    """风控阈值配置非法。"""


# value_kind: ratio=0–1；count=天数或只数
_FIELD_META: list[dict[str, Any]] = [
    {
        "key": "single_holding_loss_soft",
        "group": "intraday",
        "label": "单只持仓亏损·软",
        "desc": "某只持仓浮盈比例触及此值则提醒。优先用持仓浮盈比例，否则浮盈÷成本金额。",
        "value_kind": "ratio",
        "default": 0.04,
        "min": 0.0,
        "max": 1.0,
        "pair": "single_holding_loss_hard",
        "role": "soft",
    },
    {
        "key": "single_holding_loss_hard",
        "group": "intraday",
        "label": "单只持仓亏损·硬",
        "desc": "某只持仓浮盈比例触及此值则发风控禁止买入。",
        "value_kind": "ratio",
        "default": 0.06,
        "min": 0.0,
        "max": 1.0,
        "pair": "single_holding_loss_soft",
        "role": "hard",
    },
    {
        "key": "book_loss_soft",
        "group": "intraday",
        "label": "总仓位亏损·软",
        "desc": "当日账号快照的当日盈亏比触及此值则提醒。无当日快照不计算。",
        "value_kind": "ratio",
        "default": 0.02,
        "min": 0.0,
        "max": 1.0,
        "pair": "book_loss_hard",
        "role": "soft",
    },
    {
        "key": "book_loss_hard",
        "group": "intraday",
        "label": "总仓位亏损·硬",
        "desc": "当日账号快照的当日盈亏比触及此值则发风控禁止买入。",
        "value_kind": "ratio",
        "default": 0.04,
        "min": 0.0,
        "max": 1.0,
        "pair": "book_loss_soft",
        "role": "hard",
    },
    {
        "key": "losing_days_soft",
        "group": "multi_day",
        "label": "连亏天数·软",
        "desc": "账号快照当日盈亏连续为负的交易日数触及此值则提醒。缺快照打断连续。",
        "value_kind": "count",
        "default": 3.0,
        "min": 1.0,
        "max": 30.0,
        "pair": "losing_days_hard",
        "role": "soft",
    },
    {
        "key": "losing_days_hard",
        "group": "multi_day",
        "label": "连亏天数·硬",
        "desc": "连亏天数触及此值则发风控禁止买入。",
        "value_kind": "count",
        "default": 5.0,
        "min": 1.0,
        "max": 30.0,
        "pair": "losing_days_soft",
        "role": "hard",
    },
    {
        "key": "losing_holdings_union_soft",
        "group": "multi_day",
        "label": "亏损持仓累积·软",
        "desc": f"近 {UNION_WINDOW_DAYS} 个有持仓快照的交易日里，浮盈<0 的代码并集只数触及此值则提醒。",
        "value_kind": "count",
        "default": 3.0,
        "min": 1.0,
        "max": 100.0,
        "pair": "losing_holdings_union_hard",
        "role": "soft",
    },
    {
        "key": "losing_holdings_union_hard",
        "group": "multi_day",
        "label": "亏损持仓累积·硬",
        "desc": "并集只数触及此值则发风控禁止买入，meta 附清仓信息。",
        "value_kind": "count",
        "default": 5.0,
        "min": 1.0,
        "max": 100.0,
        "pair": "losing_holdings_union_soft",
        "role": "hard",
    },
    {
        "key": "max_dd_soft",
        "group": "multi_day",
        "label": "峰值回撤·软",
        "desc": "账户权益相对历史峰值的落差触及此值则提醒。",
        "value_kind": "ratio",
        "default": 0.08,
        "min": 0.0,
        "max": 1.0,
        "pair": "max_dd_hard",
        "role": "soft",
    },
    {
        "key": "max_dd_hard",
        "group": "multi_day",
        "label": "峰值回撤·硬",
        "desc": "峰值回撤触及此值则发风控禁止买入。",
        "value_kind": "ratio",
        "default": 0.12,
        "min": 0.0,
        "max": 1.0,
        "pair": "max_dd_soft",
        "role": "hard",
    },
]

_GROUPS = (
    {"id": "intraday", "label": "当日", "desc": "单只持仓亏损、总仓位亏损。总仓位亏损只读当日账号快照。"},
    {"id": "multi_day", "label": "跨多日", "desc": "连亏天数、亏损持仓累积（窗口固定 3 天）、峰值回撤。"},
)

_ROWS: tuple[dict[str, str], ...] = (
    {
        "id": "single_holding_loss",
        "group": "intraday",
        "label": "单只持仓亏损",
        "desc": "优先用持仓浮盈比例，否则浮盈÷成本金额。",
        "soft": "single_holding_loss_soft",
        "hard": "single_holding_loss_hard",
    },
    {
        "id": "book_loss",
        "group": "intraday",
        "label": "总仓位亏损",
        "desc": "读当日账号快照盈亏比；无快照不计算。",
        "soft": "book_loss_soft",
        "hard": "book_loss_hard",
    },
    {
        "id": "losing_days",
        "group": "multi_day",
        "label": "连亏天数",
        "desc": "当日盈亏连续为负的交易日数；缺快照打断。",
        "soft": "losing_days_soft",
        "hard": "losing_days_hard",
    },
    {
        "id": "losing_holdings_union",
        "group": "multi_day",
        "label": "亏损持仓累积",
        "desc": f"近 {UNION_WINDOW_DAYS} 日浮盈<0 的代码并集只数。",
        "soft": "losing_holdings_union_soft",
        "hard": "losing_holdings_union_hard",
    },
    {
        "id": "max_dd",
        "group": "multi_day",
        "label": "峰值回撤",
        "desc": "权益相对历史峰值的落差。",
        "soft": "max_dd_soft",
        "hard": "max_dd_hard",
    },
)

_DEFAULTS = {m["key"]: float(m["default"]) for m in _FIELD_META}
_PAIRS = tuple((row["soft"], row["hard"]) for row in _ROWS)
_META_BY_KEY = {m["key"]: m for m in _FIELD_META}


def _coerce(meta: dict[str, Any], raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError) as exc:
        raise RiskGuardConfigError(f"{meta['label']} 须为数字") from exc
    if v != v:  # NaN
        raise RiskGuardConfigError(f"{meta['label']} 须为数字")
    lo = float(meta["min"])
    hi = float(meta["max"])
    if v < lo or v > hi:
        raise RiskGuardConfigError(f"{meta['label']} 须在 {lo:g}–{hi:g}")
    if meta["value_kind"] == "count":
        if abs(v - round(v)) > 1e-9:
            raise RiskGuardConfigError(f"{meta['label']} 须为整数")
        v = float(int(round(v)))
    return v


def _overlay_from_raw(raw: dict, *, strict: bool) -> dict[str, float]:
    meta_by_key = {m["key"]: m for m in _FIELD_META}
    out: dict[str, float] = {}
    for key, val in raw.items():
        meta = meta_by_key.get(str(key))
        if meta is None:
            if strict:
                raise RiskGuardConfigError(f"未知阈值 {key}")
            continue
        out[str(key)] = _coerce(meta, val)
    return out


def _validate_pairs(values: dict[str, float]) -> None:
    for soft_k, hard_k in _PAIRS:
        if values[soft_k] > values[hard_k] + 1e-12:
            raise RiskGuardConfigError("软阈值不能大于对应硬阈值")


def _load_overlay() -> dict[str, float]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return dict(_CACHE)
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        overlay: dict[str, float] = {}
    else:
        raw = d.get("thresholds") if isinstance(d, dict) else None
        overlay = _overlay_from_raw(raw, strict=False) if isinstance(raw, dict) else {}
    with _LOCK:
        _CACHE = dict(overlay)
    return overlay


def resolved() -> dict[str, float]:
    out = dict(_DEFAULTS)
    out.update(_load_overlay())
    return out


def save_values(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise RiskGuardConfigError("thresholds 须为对象")
    merged = resolved()
    merged.update(_overlay_from_raw(raw, strict=True))
    _validate_pairs(merged)
    overlay = {k: v for k, v in merged.items() if abs(v - _DEFAULTS[k]) > 1e-9}
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "thresholds": overlay}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入风控阈值失败：{_CONFIG_PATH}")
    global _CACHE
    with _LOCK:
        _CACHE = dict(overlay)
    return resolved()


def reset_values() -> dict[str, float]:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "thresholds": {}}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入风控阈值失败：{_CONFIG_PATH}")
    global _CACHE
    with _LOCK:
        _CACHE = {}
    return resolved()


def _export_side(meta: dict[str, Any], values: dict[str, float]) -> dict[str, Any]:
    key = meta["key"]
    return {
        "key": key,
        "value": values[key],
        "min": meta["min"],
        "max": meta["max"],
    }


def export_config() -> dict[str, Any]:
    values = resolved()
    groups_out = []
    for g in _GROUPS:
        rows = []
        for row in _ROWS:
            if row["group"] != g["id"]:
                continue
            soft_meta = _META_BY_KEY[row["soft"]]
            hard_meta = _META_BY_KEY[row["hard"]]
            rows.append({
                "id": row["id"],
                "label": row["label"],
                "desc": row["desc"],
                "value_kind": soft_meta["value_kind"],
                "soft": _export_side(soft_meta, values),
                "hard": _export_side(hard_meta, values),
            })
        groups_out.append({"id": g["id"], "label": g["label"], "desc": g["desc"], "rows": rows})
    return {
        "schema": _SCHEMA,
        "union_window_days": UNION_WINDOW_DAYS,
        "groups": groups_out,
        "thresholds": values,
    }
