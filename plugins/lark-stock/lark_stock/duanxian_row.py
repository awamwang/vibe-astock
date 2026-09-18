"""把 live.snapshot 钩子 payload 收成短线盘面一行。"""

from __future__ import annotations

from typing import Any

from .config import DUANXIAN_BITABLE_COLUMNS


def _block(payload: dict[str, Any], key: str) -> dict[str, Any]:
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, dict):
        return {}
    wrap = sources.get(key) or {}
    if not isinstance(wrap, dict):
        return {}
    data = wrap.get("data")
    return data if isinstance(data, dict) else {}


def _num(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return int(value) if isinstance(value, float) and value.is_integer() else value
    try:
        text = str(value).strip().replace("%", "").replace(",", "")
        if not text:
            return None
        number = float(text)
        if number.is_integer():
            return int(number)
        return number
    except (TypeError, ValueError):
        return None


def _yi(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(float(number) / 1e8, 2)


def _pct100(value: Any) -> float | None:
    """0~1 比例写成百分数。"""
    number = _num(value)
    if number is None:
        return None
    return round(float(number) * 100, 2)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(parts) or None
    text = str(value).strip()
    return text or None


def _first_num(*values: Any) -> float | int | None:
    for value in values:
        number = _num(value)
        if number is not None:
            return number
    return None


def extract_duanxian_values(payload: dict[str, Any], *, date: str) -> dict[str, Any]:
    """返回 ENV 键 → 写入值。缺数的键不出现。"""
    board = _block(payload, "short_board")
    today = board.get("today") if isinstance(board.get("today"), dict) else {}
    emo = _block(payload, "live_emotion")
    zte = _block(payload, "live_zt_effect")
    sent = _block(payload, "market_sentiment")
    reso = _block(payload, "board_emotion_resonance")
    default = reso.get("default") if isinstance(reso.get("default"), dict) else {}

    leader = _text(today.get("qcj_leader"))
    top = _text(today.get("qcj_leader_top"))
    if leader and top:
        leader_out: str | None = f"{leader} · {top}"
    else:
        leader_out = leader or top

    score = _num(default.get("score"))
    label = _text(default.get("label"))
    resonance: Any
    if score is not None and label:
        resonance = f"{float(score):.3f} {label}"
    elif score is not None:
        resonance = round(float(score), 3)
    else:
        resonance = label

    mapping: dict[str, Any] = {
        "DUANXIAN_DATE_BITABLE_KEY_NAME": date,
        "DUANXIAN_TEMPERATURE_BITABLE_KEY_NAME": _num(today.get("temperature")),
        "DUANXIAN_BREADTH_BITABLE_KEY_NAME": _text(sent.get("breadth")),
        "DUANXIAN_SPECULATION_BITABLE_KEY_NAME": _text(sent.get("speculation")),
        "DUANXIAN_UP_BITABLE_KEY_NAME": _first_num(sent.get("up"), today.get("n_up")),
        "DUANXIAN_DOWN_BITABLE_KEY_NAME": _first_num(sent.get("down"), today.get("n_down")),
        "DUANXIAN_FLAT_BITABLE_KEY_NAME": _num(sent.get("flat")),
        "DUANXIAN_ACTIVE_BITABLE_KEY_NAME": _text(sent.get("active")),
        "DUANXIAN_SH_VOLUME_BITABLE_KEY_NAME": _yi(today.get("v_sh")),
        "DUANXIAN_A_VOLUME_BITABLE_KEY_NAME": _yi(today.get("v_ca")),
        "DUANXIAN_MAIN_INFLOW_BITABLE_KEY_NAME": _yi(today.get("m_net")),
        "DUANXIAN_VOL_RATIO_5D_BITABLE_KEY_NAME": _num(today.get("vol_ratio_5d")),
        "DUANXIAN_VOL_RATIO_20D_BITABLE_KEY_NAME": _num(today.get("vol_ratio_20d")),
        "DUANXIAN_EMOTION_SCORE_BITABLE_KEY_NAME": _num(today.get("qcj_temp")),
        "DUANXIAN_PHASE_BITABLE_KEY_NAME": _text(today.get("qcj_level")),
        "DUANXIAN_LIMIT_UP_BITABLE_KEY_NAME": _first_num(today.get("qcj_zt"), emo.get("zt_count")),
        "DUANXIAN_LIMIT_DOWN_BITABLE_KEY_NAME": _first_num(today.get("qcj_dt"), emo.get("dt_count")),
        "DUANXIAN_LEADER_BITABLE_KEY_NAME": leader_out,
        "DUANXIAN_THEMES_BITABLE_KEY_NAME": _text(today.get("qcj_themes")),
        "DUANXIAN_OPEN_SUCCESS_BITABLE_KEY_NAME": _pct100(zte.get("open_success_rate")),
        "DUANXIAN_ZT_PREMIUM_BITABLE_KEY_NAME": _num(today.get("zt_avg_zr")),
        "DUANXIAN_LIANBAN_PREMIUM_BITABLE_KEY_NAME": _num(zte.get("consec_premium_avg")),
        "DUANXIAN_PROMOTION_BITABLE_KEY_NAME": _pct100(emo.get("promotion_rate")),
        "DUANXIAN_BROKEN_RATE_BITABLE_KEY_NAME": _num(today.get("broken_r")),
        "DUANXIAN_MAX_BOARDS_BITABLE_KEY_NAME": _num(emo.get("max_boards")),
        "DUANXIAN_LIANBAN_COUNT_BITABLE_KEY_NAME": _num(emo.get("lianban_count")),
        "DUANXIAN_ZT_DEEP_LOSS_BITABLE_KEY_NAME": _num(zte.get("deep_loss_5_count")),
        "DUANXIAN_BROKEN_COUNT_BITABLE_KEY_NAME": _num(emo.get("zb_count")),
        "DUANXIAN_RESONANCE_BITABLE_KEY_NAME": resonance,
    }
    return {key: value for key, value in mapping.items() if value is not None and value != ""}


def to_bitable_fields(values: dict[str, Any], columns: dict[str, str]) -> dict[str, Any]:
    """把 ENV 键换成飞书列名。列名为空的项跳过。"""
    fields: dict[str, Any] = {}
    for col in DUANXIAN_BITABLE_COLUMNS:
        name = str((columns or {}).get(col.key) or "").strip()
        if not name or col.key not in values:
            continue
        fields[name] = values[col.key]
    return fields
