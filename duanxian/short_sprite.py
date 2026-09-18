"""短线精灵：随盘涨速 / 突破 / 跌破。

只读环境条、昨涨停效应、打板情绪共振默认分、短线风格指数的现有 snapshot，
不新开行情源，无常驻轮询。检测算法在本模块；HTTP 只做薄封装。
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os
import threading
import uuid
from typing import Any, Callable, Optional

from . import paths as _paths
from .util import atomic_write_json, china_now

SLOT_SEC = 20
RING_SEC = 6 * 60
SPEED_SEC = 5 * 60
OPEN_HMS = (9, 30, 0)
_SCHEMA = 1

_CFG_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()

_CONFIG_DIR = ""
_CONFIG_PATH = ""
_CACHE_DIR = ""
_STATE_PATH = ""

_now_fn: Callable[[], _dt.datetime] | None = None
_read_short_board: Callable[[], dict] | None = None
_read_zt_effect: Callable[[], dict] | None = None
_read_resonance: Callable[[], dict] | None = None
_read_style_indices: Callable[[], dict] | None = None

_cfg_cache: Optional[dict[str, dict[str, Any]]] = None

_enabled = True
_state_loaded = False
_session: Optional[str] = None
_ring: list[tuple[float, dict[str, float]]] = []
_open: dict[str, dict[str, Any]] = {}
_hits: list[dict[str, Any]] = []
_prev_speed: dict[str, float] = {}
_prev_vs: dict[str, float] = {}
_armed: dict[str, dict[str, bool]] = {}
_last_new_hits: list[dict[str, Any]] = []
_last_meta: dict[str, Any] = {}
_last_readings: dict[str, dict[str, Any]] = {}


class ShortSpriteConfigError(ValueError):
    """短线精灵配置非法。"""


# 盘面序列 + 指定风格项 + 风格共用行。unit: pct / count / temp / resonance
BOARD_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "consec_premium",
        "label": "连板溢价",
        "unit": "pct",
        "reversed": False,
        "speed_up": 0.5,
        "speed_down": -0.5,
        "break_up": 3.0,
        "break_down": -3.0,
        "hysteresis": 0.3,
    },
    {
        "key": "zt_premium",
        "label": "涨停溢价",
        "unit": "pct",
        "reversed": False,
        "speed_up": 0.5,
        "speed_down": -0.5,
        "break_up": 3.0,
        "break_down": -3.0,
        "hysteresis": 0.3,
    },
    {
        "key": "env_n_up",
        "label": "环境条上涨数",
        "unit": "count",
        "reversed": False,
        "speed_up": 150.0,
        "speed_down": -150.0,
        "break_up": 400.0,
        "break_down": -400.0,
        "hysteresis": 40.0,
    },
    {
        "key": "env_n_down",
        "label": "环境条下跌数",
        "unit": "count",
        "reversed": True,
        "speed_up": 150.0,
        "speed_down": -150.0,
        "break_up": 400.0,
        "break_down": -400.0,
        "hysteresis": 40.0,
    },
    {
        "key": "temperature",
        "label": "情绪温度",
        "unit": "temp",
        "reversed": False,
        "speed_up": 8.0,
        "speed_down": -8.0,
        "break_up": 15.0,
        "break_down": -15.0,
        "hysteresis": 3.0,
        "break_ladder": True,
    },
    {
        "key": "qcj_temp",
        "label": "情绪分",
        "unit": "temp",
        "reversed": False,
        "speed_up": 8.0,
        "speed_down": -8.0,
        "break_up": 15.0,
        "break_down": -15.0,
        "hysteresis": 3.0,
        "break_ladder": True,
    },
    {
        "key": "resonance",
        "label": "打板情绪共振",
        "unit": "resonance",
        "reversed": False,
        "speed_up": 0.1,
        "speed_down": -0.1,
        "break_up": 0.40,
        "break_down": -0.40,
        "hysteresis": 0.08,
    },
)

_STYLE_THRESH: dict[str, float] = {
    "speed_up": 1.5,
    "speed_down": -1.5,
    "break_up": 3.0,
    "break_down": -3.0,
    "hysteresis": 0.3,
}

_STYLE_WATCH_THRESH: dict[str, float] = {
    "speed_up": 1.0,
    "speed_down": -1.0,
    "break_up": 2.0,
    "break_down": -2.0,
    "hysteresis": 0.3,
}

STYLE_SPEC: dict[str, Any] = {
    "key": "style_indices",
    "label": "短线风格指数",
    "unit": "pct",
    "reversed": False,
    **_STYLE_THRESH,
}

# 单独成行的风格项；其余风格指数仍走 STYLE_SPEC 共用行。
STYLE_WATCH_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        "key": key,
        "label": label,
        "unit": "pct",
        "reversed": False,
        **_STYLE_WATCH_THRESH,
    }
    for key, label in (
        ("mid", "中盘股"),
        ("low_price", "低价股"),
        ("cyb", "创业板指"),
        ("small", "小盘股"),
        ("large", "大盘股"),
        ("micro", "微盘股"),
    )
)
_STYLE_WATCH_BY_KEY = {s["key"]: s for s in STYLE_WATCH_SPECS}

_RULE_KEYS = ("monitor", "voice", "speed_up", "speed_down", "break_up", "break_down", "hysteresis")
_EVENT_SPEECH = {
    "speed_up": "涨速突破",
    "speed_down": "涨速跌破",
    "break_up": "涨幅突破",
    "break_down": "涨幅跌破",
}
_EVENT_LABEL = {
    "speed_up": "涨速",
    "speed_down": "涨速",
    "break_up": "突破",
    "break_down": "跌破",
}
_ARM_KEYS = ("speed_up", "speed_down", "break_up", "break_down")
_LADDER_MAX_N = 32
_ladder_disarmed_up: dict[str, set[int]] = {}
_ladder_disarmed_down: dict[str, set[int]] = {}


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CONFIG_DIR, _CONFIG_PATH, _CACHE_DIR, _STATE_PATH
    _CONFIG_DIR = str(_paths.config_dir())
    _CONFIG_PATH = os.path.join(_CONFIG_DIR, "short_sprite.json")
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "short_sprite")
    _STATE_PATH = os.path.join(_CACHE_DIR, "state.json")


def unix_slot_start(ts: float, slot_sec: int = SLOT_SEC) -> int:
    """含 ts 的 Unix 槽起点（秒）。"""
    return int(ts) // int(slot_sec) * int(slot_sec)


def next_unix_slot(ts: float, slot_sec: int = SLOT_SEC) -> int:
    """严格晚于 ts 的下一拍 Unix 秒。已落在槽点则再等一整槽。"""
    start = unix_slot_start(ts, slot_sec)
    return start + int(slot_sec)


def delay_until_next_unix_slot(ts: float, slot_sec: int = SLOT_SEC) -> float:
    return float(next_unix_slot(ts, slot_sec) - ts)


def _now() -> _dt.datetime:
    if _now_fn is not None:
        return _now_fn()
    return china_now()


def _epoch(now: _dt.datetime) -> float:
    if now.tzinfo is not None:
        return now.timestamp()
    return now.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=8))).timestamp()


def _iso(now: _dt.datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%S")


def _finite(v: object) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _past_open(now: _dt.datetime) -> bool:
    return (now.hour, now.minute, now.second) >= OPEN_HMS


def _default_rule(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "monitor": True,
        "voice": True,
        "speed_up": float(spec["speed_up"]),
        "speed_down": float(spec["speed_down"]),
        "break_up": float(spec["break_up"]),
        "break_down": float(spec["break_down"]),
        "hysteresis": float(spec["hysteresis"]),
    }


def _all_specs() -> tuple[dict[str, Any], ...]:
    return (*BOARD_SPECS, *STYLE_WATCH_SPECS, STYLE_SPEC)


def default_rules() -> dict[str, dict[str, Any]]:
    return {s["key"]: _default_rule(s) for s in _all_specs()}


def _specs_by_key() -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in _all_specs()}


def _as_bool(v: object, label: str) -> bool:
    if isinstance(v, bool):
        return v
    if v in (0, 1, "0", "1", "true", "false", "True", "False"):
        if v in (0, "0", "false", "False"):
            return False
        if v in (1, "1", "true", "True"):
            return True
    raise ShortSpriteConfigError(f"{label}须为布尔")


def _as_finite(v: object, label: str) -> float:
    x = _finite(v)
    if x is None:
        raise ShortSpriteConfigError(f"{label}须为有限数字")
    return x


def _normalize_rule(raw: object, spec: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    out = _default_rule(spec)
    if raw is None:
        return out
    if not isinstance(raw, dict):
        if strict:
            raise ShortSpriteConfigError(f"{spec['label']} 须为对象")
        return out
    label = spec["label"]
    try:
        if "monitor" in raw and raw["monitor"] is not None:
            out["monitor"] = _as_bool(raw["monitor"], f"{label}·监控")
        if "voice" in raw and raw["voice"] is not None:
            out["voice"] = _as_bool(raw["voice"], f"{label}·语音")
        for key, name in (
            ("speed_up", "上速阈"),
            ("speed_down", "下速阈"),
            ("break_up", "突破上阈"),
            ("break_down", "跌破下阈"),
            ("hysteresis", "回差"),
        ):
            if key in raw and raw[key] is not None:
                out[key] = _as_finite(raw[key], f"{label}·{name}")
        if out["hysteresis"] < 0:
            raise ShortSpriteConfigError(f"{label}·回差不能为负")
    except ShortSpriteConfigError:
        if strict:
            raise
    return out


def _overlay_from_raw(raw: object, *, strict: bool) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise ShortSpriteConfigError("rules 须为对象")
        return {}
    specs = _specs_by_key()
    out: dict[str, dict[str, Any]] = {}
    for key, val in raw.items():
        k = str(key).strip()
        spec = specs.get(k)
        if spec is None:
            if strict:
                raise ShortSpriteConfigError(f"未知规则 {k!r}")
            continue
        out[k] = _normalize_rule(val, spec, strict=strict)
    return out


def _read_overlay() -> dict[str, dict[str, Any]]:
    if not os.path.isfile(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            env = json.load(fh)
        if not isinstance(env, dict):
            return {}
        return _overlay_from_raw(env.get("rules"), strict=False)
    except Exception:  # noqa: BLE001
        return {}


def load_overlay() -> dict[str, dict[str, Any]]:
    global _cfg_cache
    if _cfg_cache is not None:
        return copy.deepcopy(_cfg_cache)
    with _CFG_LOCK:
        if _cfg_cache is None:
            _cfg_cache = _read_overlay()
        return copy.deepcopy(_cfg_cache)


def resolved_rules() -> dict[str, dict[str, Any]]:
    out = default_rules()
    overlay = load_overlay()
    for key, rule in overlay.items():
        out[key] = rule
    return out


def _rule_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    for k in _RULE_KEYS:
        av, bv = a[k], b[k]
        if k in ("monitor", "voice"):
            if bool(av) != bool(bv):
                return False
        elif abs(float(av) - float(bv)) > 1e-12:
            return False
    return True


def save_rules(raw: object) -> dict[str, dict[str, Any]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ShortSpriteConfigError("rules 须为对象")
    merged = resolved_rules()
    overlay_in = _overlay_from_raw(raw, strict=True)
    merged.update(overlay_in)
    defaults = default_rules()
    overlay = {k: v for k, v in merged.items() if not _rule_equal(v, defaults[k])}
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "rules": overlay}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入短线精灵配置失败：{_CONFIG_PATH}")
    global _cfg_cache
    with _CFG_LOCK:
        _cfg_cache = copy.deepcopy(overlay)
    return merged


def reset_rules() -> dict[str, dict[str, Any]]:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    payload = {"schema": _SCHEMA, "rules": {}}
    if not atomic_write_json(_CONFIG_PATH, payload):
        raise OSError(f"写入短线精灵配置失败：{_CONFIG_PATH}")
    global _cfg_cache
    with _CFG_LOCK:
        _cfg_cache = {}
    return default_rules()


def export_config() -> dict[str, Any]:
    values = resolved_rules()
    rules = []
    for spec in _all_specs():
        key = spec["key"]
        rule = values[key]
        rules.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            "reversed": bool(spec["reversed"]),
            **rule,
            "defaults": _default_rule(spec),
        })
    return {
        "schema": _SCHEMA,
        "path": _CONFIG_PATH,
        "rules": rules,
        "values": values,
        "defaults": default_rules(),
    }


def _day_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _read_json(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _call_reader(override: Callable[[], dict] | None, import_name: str) -> dict:
    if override is not None:
        out = override()
        return out if isinstance(out, dict) else {}
    from duanxian import board_emotion_resonance, live_zt_effect, short_board, style_indices

    mod = {
        "short_board": short_board,
        "live_zt_effect": live_zt_effect,
        "board_emotion_resonance": board_emotion_resonance,
        "style_indices": style_indices,
    }[import_name]
    out = mod.snapshot()
    return out if isinstance(out, dict) else {}


def _fetch_market() -> dict[str, dict]:
    return {
        "short_board": _call_reader(_read_short_board, "short_board"),
        "zt": _call_reader(_read_zt_effect, "live_zt_effect"),
        "resonance": _call_reader(_read_resonance, "board_emotion_resonance"),
        "style": _call_reader(_read_style_indices, "style_indices"),
    }


def _style_seq_id(key: str) -> str:
    return f"style:{key}"


def _config_key_for(seq_id: str) -> str:
    if seq_id.startswith("style:"):
        item_key = seq_id[6:]
        if item_key in _STYLE_WATCH_BY_KEY:
            return item_key
        return STYLE_SPEC["key"]
    return seq_id


def _extract(market: dict[str, dict]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    sb = market.get("short_board") or {}
    zt = market.get("zt") or {}
    res = market.get("resonance") or {}
    st = market.get("style") or {}
    today = sb.get("today") if isinstance(sb.get("today"), dict) else {}
    default = res.get("default") if isinstance(res.get("default"), dict) else {}

    date = sb.get("date") or zt.get("date") or st.get("date") or res.get("date")
    is_live = bool(sb.get("is_live") if "is_live" in sb else (
        zt.get("is_live") if "is_live" in zt else st.get("is_live", False)
    ))
    settled = bool(sb.get("settled") if "settled" in sb else (
        zt.get("settled") if "settled" in zt else st.get("settled", False)
    ))
    meta = {
        "date": date if isinstance(date, str) and date else None,
        "is_live": is_live,
        "settled": settled,
    }

    readings: dict[str, dict[str, Any]] = {}

    def add(seq_id: str, spec: dict[str, Any], value: object, *, name: str | None = None) -> None:
        readings[seq_id] = {
            "id": seq_id,
            "name": name or spec["label"],
            "unit": spec["unit"],
            "reversed": bool(spec["reversed"]),
            "kind": "style" if seq_id.startswith("style:") else "board",
            "value": _finite(value),
            "config_key": spec["key"],
        }

    add("consec_premium", BOARD_SPECS[0], zt.get("consec_premium_avg"))
    add("zt_premium", BOARD_SPECS[1], today.get("zt_avg_zr"))
    add("env_n_up", BOARD_SPECS[2], today.get("n_up"))
    add("env_n_down", BOARD_SPECS[3], today.get("n_down"))
    add("temperature", BOARD_SPECS[4], today.get("temperature"))
    add("qcj_temp", BOARD_SPECS[5], today.get("qcj_temp"))
    add("resonance", BOARD_SPECS[6], default.get("score"))

    unavailable = {
        str(x.get("key"))
        for x in (st.get("unavailable") or [])
        if isinstance(x, dict) and x.get("key")
    }
    for group in st.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if not key or key in unavailable:
                continue
            if item.get("available") is False:
                continue
            val = _finite(item.get("change_pct"))
            if val is None:
                continue
            spec = _STYLE_WATCH_BY_KEY.get(key) or STYLE_SPEC
            add(_style_seq_id(key), spec, val, name=str(item.get("name") or key))

    return meta, readings


def _fmt_speech_value(value: float, unit: str) -> str:
    if unit == "pct":
        return f"{value:.1f}%"
    if unit == "count":
        return f"{int(round(value))}家"
    if unit == "resonance":
        return f"{value:.3f}"
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def format_speech(name: str, event: str, value: float, unit: str) -> str:
    verb = _EVENT_SPEECH[event]
    return f"{name}，{verb}{_fmt_speech_value(value, unit)}"


def _armed_default() -> dict[str, bool]:
    return {k: True for k in _ARM_KEYS}


def _prune_ring(now_ts: float) -> None:
    cutoff = now_ts - RING_SEC
    keep = [row for row in _ring if row[0] >= cutoff]
    _ring.clear()
    _ring.extend(keep)


def _speed_for(seq_id: str, now_ts: float) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """返回 (speed, from_value, from_ts)。点不足则全 None。"""
    if not _ring:
        return None, None, None
    current = None
    for ts, vals in reversed(_ring):
        if seq_id in vals:
            current = vals[seq_id]
            break
    if current is None:
        return None, None, None
    target = now_ts - SPEED_SEC
    base_ts = None
    base_val = None
    for ts, vals in _ring:
        if ts > target:
            break
        if seq_id in vals:
            base_ts = ts
            base_val = vals[seq_id]
    if base_ts is None or base_val is None:
        return None, None, None
    return current - base_val, base_val, base_ts


def _cross_up(prev: Optional[float], curr: float, th: float) -> bool:
    if prev is None:
        return False
    return prev <= th < curr


def _cross_down(prev: Optional[float], curr: float, th: float) -> bool:
    if prev is None:
        return False
    return prev >= th > curr


def _rungs_crossed_up(prev: Optional[float], curr: float, step: float) -> list[int]:
    """prev <= n*step < curr 的正整数 n。"""
    if prev is None or not math.isfinite(prev) or not math.isfinite(curr):
        return []
    if not math.isfinite(step) or step <= 0:
        return []
    out: list[int] = []
    for n in range(1, _LADDER_MAX_N + 1):
        th = n * step
        if not th < curr:
            break
        if prev <= th:
            out.append(n)
    return out


def _rungs_crossed_down(prev: Optional[float], curr: float, step: float) -> list[int]:
    """prev >= n*step > curr 的正整数 n。step 为负。"""
    if prev is None or not math.isfinite(prev) or not math.isfinite(curr):
        return []
    if not math.isfinite(step) or step >= 0:
        return []
    out: list[int] = []
    for n in range(1, _LADDER_MAX_N + 1):
        th = n * step
        if not th > curr:
            break
        if prev >= th:
            out.append(n)
    return out


def _apply_break_ladder(
    seq_id: str,
    vs_open: float,
    prev_v: Optional[float],
    rule: dict[str, Any],
    hyst: float,
    emit: Callable[[str, float], None],
) -> None:
    up_step = float(rule["break_up"])
    down_step = float(rule["break_down"])
    dis_up = _ladder_disarmed_up.setdefault(seq_id, set())
    dis_down = _ladder_disarmed_down.setdefault(seq_id, set())
    if up_step > 0:
        for n in list(dis_up):
            if vs_open <= n * up_step - hyst:
                dis_up.discard(n)
        for n in _rungs_crossed_up(prev_v, vs_open, up_step):
            if n in dis_up:
                continue
            emit("break_up", n * up_step)
            dis_up.add(n)
    if down_step < 0:
        for n in list(dis_down):
            if vs_open >= n * down_step + hyst:
                dis_down.discard(n)
        for n in _rungs_crossed_down(prev_v, vs_open, down_step):
            if n in dis_down:
                continue
            emit("break_down", n * down_step)
            dis_down.add(n)


def _hit_record(
    *,
    now: _dt.datetime,
    rec: dict[str, Any],
    event: str,
    value: float,
    voice: bool,
    from_value: Optional[float] = None,
    from_ts: Optional[float] = None,
    to_value: Optional[float] = None,
) -> dict[str, Any]:
    name = rec["name"]
    unit = rec["unit"]
    hit: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "ts": _iso(now),
        "epoch": _epoch(now),
        "seq_id": rec["id"],
        "name": name,
        "event": event,
        "event_label": _EVENT_LABEL[event],
        "direction": "up" if event.endswith("_up") else "down",
        "reversed": bool(rec["reversed"]),
        "value": value,
        "unit": unit,
        "speech": format_speech(name, event, value, unit),
        "voice": bool(voice),
    }
    if event in ("speed_up", "speed_down") and from_value is not None and to_value is not None:
        hit["from_value"] = from_value
        hit["to_value"] = to_value
        if from_ts is not None:
            hit["from_ts"] = from_ts
    return hit


def _switch_session(date: str, payload: dict[str, Any]) -> None:
    global _session
    _session = date
    _ring.clear()
    _prev_speed.clear()
    _prev_vs.clear()
    _armed.clear()
    _ladder_disarmed_up.clear()
    _ladder_disarmed_down.clear()
    _open.clear()
    _hits.clear()
    opens = payload.get("open") if isinstance(payload.get("open"), dict) else {}
    for key, rec in opens.items():
        if not isinstance(rec, dict):
            continue
        val = _finite(rec.get("value"))
        if val is None:
            continue
        _open[str(key)] = {"value": val, "ts": rec.get("ts")}
    hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
    for hit in hits:
        if isinstance(hit, dict) and hit.get("id"):
            _hits.append(dict(hit))


def _day_payload() -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "date": _session,
        "open": copy.deepcopy(_open),
        "hits": copy.deepcopy(_hits),
    }


def _copy_view(rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    now_meta = dict(_last_meta)
    readings = _last_readings
    now_ts = _epoch(_now()) if _session else 0.0
    sequences = []
    for seq_id, rec in readings.items():
        cfg_key = rec["config_key"]
        spec = _specs_by_key().get(cfg_key) or STYLE_SPEC
        rule = rules.get(cfg_key) or _default_rule(spec)
        current = rec["value"]
        open_rec = _open.get(seq_id)
        open_val = open_rec["value"] if open_rec else None
        vs_open = None if current is None or open_val is None else current - open_val
        speed, speed_from, speed_from_ts = _speed_for(seq_id, now_ts)
        samples = [
            {"ts": ts, "value": vals[seq_id]}
            for ts, vals in _ring
            if seq_id in vals
        ]
        last_hit = None
        for hit in reversed(_hits):
            if hit.get("seq_id") == seq_id:
                last_hit = dict(hit)
                break
        th = {
            "speed_up": rule["speed_up"],
            "speed_down": rule["speed_down"],
            "break_up": rule["break_up"],
            "break_down": rule["break_down"],
            "hysteresis": rule["hysteresis"],
        }
        outside = {
            "speed_up": speed is not None and speed > th["speed_up"],
            "speed_down": speed is not None and speed < th["speed_down"],
            "break_up": vs_open is not None and vs_open > th["break_up"],
            "break_down": vs_open is not None and vs_open < th["break_down"],
        }
        sequences.append({
            "id": seq_id,
            "name": rec["name"],
            "kind": rec["kind"],
            "unit": rec["unit"],
            "reversed": rec["reversed"],
            "monitored": bool(rule["monitor"]),
            "voice": bool(rule["voice"]),
            "open": open_val,
            "open_ts": open_rec.get("ts") if open_rec else None,
            "current": current,
            "vs_open": vs_open,
            "speed": speed,
            "speed_from": speed_from,
            "speed_from_ts": speed_from_ts,
            "thresholds": th,
            "outside": outside,
            "last_hit": last_hit,
            "samples": samples,
        })
    order = {s["key"]: i for i, s in enumerate(BOARD_SPECS)}
    order.update({
        _style_seq_id(s["key"]): len(BOARD_SPECS) + i
        for i, s in enumerate(STYLE_WATCH_SPECS)
    })
    sequences.sort(key=lambda s: (order.get(s["id"], 1000), s["name"]))
    is_live = bool(now_meta.get("is_live"))
    settled = bool(now_meta.get("settled"))
    return {
        "date": _session,
        "is_live": is_live,
        "settled": settled,
        "enabled": bool(_enabled),
        "can_detect": bool(_enabled and is_live and not settled),
        "disclaimer": "命中是观察记录，不是买卖指令。",
        "sequences": sequences,
        "hits": copy.deepcopy(_hits),
        "new_hits": copy.deepcopy(_last_new_hits),
    }


def tick() -> dict[str, Any]:
    """读现有 snapshot，更新开盘/环/命中，返回详情所需中间值。"""
    global _enabled, _state_loaded, _last_meta, _last_readings, _last_new_hits
    now = _now()
    now_ts = _epoch(now)
    rules = resolved_rules()
    market = _fetch_market()
    meta, readings = _extract(market)

    state_disk = None if _state_loaded else _read_json(_STATE_PATH)
    date = meta.get("date")
    with _STATE_LOCK:
        need_day = isinstance(date, str) and bool(date) and date != _session
    day_disk = _read_json(_day_path(date)) if need_day else {}

    persist_day = None
    with _STATE_LOCK:
        if not _state_loaded:
            if "enabled" in state_disk:
                _enabled = bool(state_disk.get("enabled"))
            _state_loaded = True
        if isinstance(date, str) and date and date != _session:
            _switch_session(date, day_disk)
        _last_meta = dict(meta)
        _last_readings = readings
        _last_new_hits = []

        is_live = bool(meta.get("is_live"))
        settled = bool(meta.get("settled"))
        detect = bool(_enabled and is_live and not settled)
        past_open = _past_open(now)
        day_dirty = False

        if is_live and not settled:
            sample: dict[str, float] = {}
            for seq_id, rec in readings.items():
                val = rec["value"]
                if val is not None:
                    sample[seq_id] = val
            _prune_ring(now_ts)
            if sample:
                _ring.append((now_ts, sample))
            if past_open:
                for seq_id, rec in readings.items():
                    val = rec["value"]
                    if val is None:
                        continue
                    if seq_id not in _open:
                        _open[seq_id] = {"value": val, "ts": _iso(now)}
                        day_dirty = True

        if detect:
            for seq_id, rec in readings.items():
                current = rec["value"]
                if current is None:
                    continue
                spec = _specs_by_key().get(rec["config_key"]) or STYLE_SPEC
                rule = rules.get(rec["config_key"]) or _default_rule(spec)
                arms = _armed.setdefault(seq_id, _armed_default())
                speed, speed_from, speed_from_ts = _speed_for(seq_id, now_ts)
                open_val = _open[seq_id]["value"] if seq_id in _open else None
                vs_open = None if open_val is None else current - open_val
                hyst = float(rule["hysteresis"])
                monitored = bool(rule["monitor"])
                voice = bool(rule["voice"])

                def emit_hit(
                    event: str,
                    value: float,
                    from_value: Optional[float] = None,
                    from_ts: Optional[float] = None,
                    to_value: Optional[float] = None,
                ) -> None:
                    nonlocal day_dirty
                    if not monitored:
                        return
                    hit = _hit_record(
                        now=now,
                        rec=rec,
                        event=event,
                        value=value,
                        voice=voice,
                        from_value=from_value,
                        from_ts=from_ts,
                        to_value=to_value,
                    )
                    _hits.append(hit)
                    _last_new_hits.append(hit)
                    day_dirty = True

                def maybe_hit(
                    event: str,
                    value: float,
                    arm_key: str,
                    *,
                    from_value: Optional[float] = None,
                    from_ts: Optional[float] = None,
                    to_value: Optional[float] = None,
                ) -> None:
                    if not arms.get(arm_key, True):
                        return
                    emit_hit(
                        event,
                        value,
                        from_value=from_value,
                        from_ts=from_ts,
                        to_value=to_value,
                    )
                    arms[arm_key] = False

                prev_s = _prev_speed.get(seq_id)
                if speed is not None:
                    if _cross_up(prev_s, speed, float(rule["speed_up"])):
                        maybe_hit(
                            "speed_up",
                            speed,
                            "speed_up",
                            from_value=speed_from,
                            from_ts=speed_from_ts,
                            to_value=current,
                        )
                    if _cross_down(prev_s, speed, float(rule["speed_down"])):
                        maybe_hit(
                            "speed_down",
                            speed,
                            "speed_down",
                            from_value=speed_from,
                            from_ts=speed_from_ts,
                            to_value=current,
                        )
                    if speed <= float(rule["speed_up"]) - hyst:
                        arms["speed_up"] = True
                    if speed >= float(rule["speed_down"]) + hyst:
                        arms["speed_down"] = True
                    _prev_speed[seq_id] = speed

                prev_v = _prev_vs.get(seq_id)
                if vs_open is not None:
                    if spec.get("break_ladder"):
                        _apply_break_ladder(
                            seq_id, vs_open, prev_v, rule, hyst, emit_hit,
                        )
                    else:
                        if _cross_up(prev_v, vs_open, float(rule["break_up"])):
                            maybe_hit("break_up", vs_open, "break_up")
                        if _cross_down(prev_v, vs_open, float(rule["break_down"])):
                            maybe_hit("break_down", vs_open, "break_down")
                        if vs_open <= float(rule["break_up"]) - hyst:
                            arms["break_up"] = True
                        if vs_open >= float(rule["break_down"]) + hyst:
                            arms["break_down"] = True
                    _prev_vs[seq_id] = vs_open

        if day_dirty and _session:
            persist_day = _day_payload()
        view = _copy_view(rules)

    if persist_day is not None and _session:
        atomic_write_json(_day_path(_session), persist_day)
    return view


def snapshot() -> dict[str, Any]:
    """随带 tick 的对外缝。"""
    return tick()


def set_enabled(enabled: bool) -> dict[str, Any]:
    payload = {"schema": _SCHEMA, "enabled": bool(enabled)}
    with _STATE_LOCK:
        global _enabled, _state_loaded
        _enabled = bool(enabled)
        _state_loaded = True
    atomic_write_json(_STATE_PATH, payload)
    return snapshot()


def is_enabled() -> bool:
    with _STATE_LOCK:
        return bool(_enabled)


def _reset_runtime_state() -> None:
    """测试用：清内存。磁盘由测试把目录指到 tmp。"""
    global _cfg_cache, _enabled, _state_loaded, _session
    global _last_new_hits
    with _CFG_LOCK:
        _cfg_cache = None
    with _STATE_LOCK:
        _enabled = True
        _state_loaded = False
        _session = None
        _ring.clear()
        _open.clear()
        _hits.clear()
        _prev_speed.clear()
        _prev_vs.clear()
        _armed.clear()
        _ladder_disarmed_up.clear()
        _ladder_disarmed_down.clear()
        _last_new_hits = []
        _last_meta.clear()
        _last_readings.clear()
