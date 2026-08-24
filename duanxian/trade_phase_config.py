"""仓位预算六档的总仓、单票、提示词 —— 可分别落盘覆盖。

配置落盘：`~/.duanxian-agents/config/trade_phases.json`
未改的字段沿用内置默认：总仓用硬规则表，单票为总仓一半。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from .trade_budget import PHASES, default_caps, default_prompt
from .util import atomic_write_json

_CONFIG_DIR = os.path.expanduser("~/.duanxian-agents/config")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "trade_phases.json")
_SCHEMA = 1
_MAX_PROMPT = 500
_LOCK = threading.Lock()
_TABLE: Optional[dict[str, dict[str, Any]]] = None


class TradePhaseConfigError(ValueError):
    """仓位档位配置非法。"""


def default_row(phase: str) -> dict[str, Any]:
    total, single = default_caps(phase)
    return {
        "cap_total": total,
        "cap_single": single,
        "prompt": default_prompt(phase),
    }


def default_table() -> dict[str, dict[str, Any]]:
    return {p: default_row(p) for p in PHASES}


def _as_cap(v: object, label: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise TradePhaseConfigError(f"{label} 须为数字") from exc
    if x < 0 or x > 1:
        raise TradePhaseConfigError(f"{label} 须在 0%–100%")
    return round(x, 4)


def _as_prompt(v: object) -> str:
    s = str(v if v is not None else "").strip()
    if len(s) > _MAX_PROMPT:
        raise TradePhaseConfigError(f"提示词不超过 {_MAX_PROMPT} 个字")
    return s


def _public(phase: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "cap_total": row["cap_total"],
        "cap_single": row["cap_single"],
        "prompt": row["prompt"],
    }


def _overlay_from_raw(raw: object, *, strict: bool) -> dict[str, dict[str, Any]]:
    """把 API / 磁盘上的 phases 收成「按档位、按字段」的覆盖表。缺字段不写，留给默认值。"""
    items: list[tuple[str, dict[str, Any]]] = []
    if raw is None:
        rows: list = []
    elif isinstance(raw, dict):
        rows = [{"phase": k, **(v if isinstance(v, dict) else {})} for k, v in raw.items()]
    elif isinstance(raw, list):
        rows = raw
    else:
        if strict:
            raise TradePhaseConfigError("phases 须为数组或对象")
        return {}

    for item in rows:
        if not isinstance(item, dict):
            if strict:
                raise TradePhaseConfigError("每个档位须为对象")
            continue
        phase = str(item.get("phase") or "").strip()
        if phase not in PHASES:
            if strict:
                raise TradePhaseConfigError(f"未知档位 {phase!r}，只能是 {PHASES}")
            continue
        patch: dict[str, Any] = {}
        if "cap_total" in item and item["cap_total"] is not None:
            try:
                patch["cap_total"] = _as_cap(item["cap_total"], f"{phase} 整体仓位")
            except TradePhaseConfigError:
                if strict:
                    raise
        if "cap_single" in item and item["cap_single"] is not None:
            try:
                patch["cap_single"] = _as_cap(item["cap_single"], f"{phase} 单独仓位")
            except TradePhaseConfigError:
                if strict:
                    raise
        if "prompt" in item:
            try:
                patch["prompt"] = _as_prompt(item["prompt"])
            except TradePhaseConfigError:
                if strict:
                    raise
        items.append((phase, patch))

    out: dict[str, dict[str, Any]] = {}
    for phase, patch in items:
        if patch:
            out[phase] = patch
    return out


def _read_overlay() -> dict[str, dict[str, Any]]:
    if not os.path.isfile(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return {}
        return _overlay_from_raw(env.get("phases"), strict=False)
    except Exception:  # noqa: BLE001
        return {}


def load_overlay() -> dict[str, dict[str, Any]]:
    """读取覆盖表（带进程内缓存）；空表示全部走内置默认。"""
    global _TABLE
    if _TABLE is not None:
        return {k: dict(v) for k, v in _TABLE.items()}
    with _LOCK:
        if _TABLE is None:
            _TABLE = _read_overlay()
        return {k: dict(v) for k, v in _TABLE.items()}


def reload_overlay() -> dict[str, dict[str, Any]]:
    """丢弃缓存并重新读盘。"""
    global _TABLE
    with _LOCK:
        _TABLE = _read_overlay()
        return {k: dict(v) for k, v in _TABLE.items()}


def row_for(phase: str) -> dict[str, Any]:
    """某档的生效值：覆盖字段优先，其余用内置默认。"""
    if phase not in PHASES:
        raise ValueError(f"未知档位 {phase!r}，只能是 {PHASES}")
    row = default_row(phase)
    patch = load_overlay().get(phase) or {}
    if "cap_total" in patch:
        row["cap_total"] = patch["cap_total"]
    if "cap_single" in patch:
        row["cap_single"] = patch["cap_single"]
    if "prompt" in patch:
        row["prompt"] = patch["prompt"]
    return row


def resolved_rows() -> list[dict[str, Any]]:
    return [_public(p, row_for(p)) for p in PHASES]


def save_table(raw: object) -> list[dict[str, Any]]:
    """校验并写入覆盖表。总仓、单票、提示词可只改其中几项。"""
    overlay = _overlay_from_raw(raw, strict=True)
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {
        "schema": _SCHEMA,
        "phases": [
            {"phase": p, **overlay[p]} for p in PHASES if p in overlay
        ],
    }
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入仓位档位配置失败：{_CONFIG_PATH}")
    global _TABLE
    with _LOCK:
        _TABLE = overlay
    return resolved_rows()


def reset_table() -> list[dict[str, Any]]:
    """清除覆盖，恢复内置默认（总仓原值，单票为总仓一半）。"""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "phases": []}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入仓位档位配置失败：{_CONFIG_PATH}")
    global _TABLE
    with _LOCK:
        _TABLE = {}
    return resolved_rows()


def export_config() -> dict[str, Any]:
    """供 API / 设置页读取。"""
    return {
        "schema": _SCHEMA,
        "path": _CONFIG_PATH,
        "phases": resolved_rows(),
        "defaults": [_public(p, default_row(p)) for p in PHASES],
    }
