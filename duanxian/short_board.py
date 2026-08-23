"""短线盘面 · 环境指标条（仿开盘啦盯盘 Environment）。

数据源对齐 awam-stock `Environment` 合并逻辑：
  · 选股宝 Flash `market_indicator/line` → 情绪温度 / 涨跌家数 / 炸板率 / 涨停溢价
  · 开盘啦 `ZhangFuDetail` → 实际涨跌停、上证/A 股成交额（拿不到则降级）
  · 东财 push2 → 主力净流入
  · 腾讯行情 → 上证/深证成交额兜底（拼两市近似 A 股成交额）
  · 趣财经 qiniugu `/qng/api/v1/market` → 情绪分 / 阶段 / 涨跌停家数 / 龙头 / 主线题材

「今日 / 昨日」对比按**数据场次**，不是日历今天：
  · 左侧 = as_of（行情所属场次 / 最近已收盘日）；右侧 = as_of 的前一交易日。
  · 周末 / 盘前：展示「周五 vs 周四」，不会拿同一场跟自己比。
  · 归档只在 as_of == 日历今天且处于收盘落盘窗（收盘前 5 秒至收盘后）时写入。
无归档时前端右侧显示 `-`。主力净流入 / 成交额无归档时仍可用东财日 K、开盘啦 zr 字段补。
趣财经昨日报文优先直接取 API 历史序列中上一交易日条目。
量能对比昨日、量能 5 日/量比暂无可靠源 → 前端占位。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from . import trade_calendar
from .util import china_now

_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/short_board")
_TTL = 20.0  # 盘中指标条刷新间隔略长于 5 秒轮询，挡住叠请求
_OFFSESSION_TTL = 86400.0  # 非实时场次：已定稿，日内刷新不打上游
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_BAOER = (
    "https://flash-api.xuangubao.cn/api/market_indicator/line"
    "?fields=market_temperature,limit_up_broken_count,limit_up_broken_ratio,"
    "yesterday_limit_up_avg_pcp,rise_count,fall_count"
)
_LONGTOU = (
    "https://apphq.longhuvip.com/w1/api/index.php"
    "?a=ZhangFuDetail&apiv=w25&c=HomeDingPan&PhoneOSNew=1&"
)
_QCJ_MARKET = "https://qiniugu.com/qng/api/v1/market"
# 与 duanxian/fetchers 资金流 ut 一致
_UT = "b2884a393a59ad64002292a3e90d46a5"
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
_QCJ_UA = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://qiniugu.com/",
    "Accept": "application/json",
}


def _cached(key: str, ttl: float, build):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = build()
    if val is not None:
        with _lock:
            _cache[key] = (now, val)
    return val


def _num(v, default=None):
    try:
        if v in ("-", "", None):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _em_get(url: str, params: dict | None = None) -> Any:
    """东财请求：优先走 vr.astock.em_get（自带直连/代理自愈），否则 requests。"""
    import sys

    astock = sys.modules.get("astock")
    if astock is not None and hasattr(astock, "em_get"):
        r = astock.em_get(url, params=params, headers=_UA, timeout=12)
        return r.json()
    import requests

    r = requests.get(url, params=params, headers=_UA, timeout=12)
    r.raise_for_status()
    return r.json()


# 开盘啦对浏览器 UA 常返回空 payload；App UA 对齐 awam longTouPost
_LONGTOU_UA = {
    "User-Agent": "lhb/5.13.7 (com.kaipanla.www; build:0; iOS 16.1.0) Alamofire/4.9.1",
    "Accept": "*/*",
}


def _http_get_json(url: str, *, longtou: bool = False) -> Any:
    import requests

    headers = _LONGTOU_UA if longtou else {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=12)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# 各源拉取
# ---------------------------------------------------------------------------

def _fetch_baoer() -> dict:
    """选股宝市场温度线：取当日最新一点。"""
    try:
        raw = _http_get_json(_BAOER)
        rows = raw.get("data") or []
        if not rows:
            return {}
        last = rows[-1]
        return {
            "temperature": _num(last.get("market_temperature")),
            "n_up": int(_num(last.get("rise_count"), 0) or 0),
            "n_down": int(_num(last.get("fall_count"), 0) or 0),
            "broken_c": int(_num(last.get("limit_up_broken_count"), 0) or 0),
            # 展示用百分比（与 awam front formatEnviromentData 一致：ratio * 100）
            "broken_r": (_num(last.get("limit_up_broken_ratio")) or 0) * 100,
            "zt_avg_zr": (_num(last.get("yesterday_limit_up_avg_pcp")) or 0) * 100,
            "time_baoer": int(last.get("timestamp") or 0),
        }
    except Exception:  # noqa: BLE001
        return {}


def _fetch_longtou() -> dict:
    """开盘啦涨跌统计。errcode=0 但 info 空时返回 {}。"""
    try:
        raw = _http_get_json(_LONGTOU, longtou=True)
        info = raw.get("info")
        if not isinstance(info, dict) or not info:
            return {}
        # 成交额字段单位：万 → 元（同 awam environment store *10000）
        v_sh = _num(info.get("szln"))
        v_ca = _num(info.get("qscln"))
        v_sh_zr = _num(info.get("s_zrtj"))
        v_ca_zr = _num(info.get("q_zrtj"))
        return {
            "n_sjzt": int(_num(info.get("SJZT"), 0) or 0),
            "n_sjdt": int(_num(info.get("SJDT"), 0) or 0),
            "n_zt": int(_num(info.get("ZT"), 0) or 0),
            "n_dt": int(_num(info.get("DT"), 0) or 0),
            "n_up": int(_num(info.get("SZJS"), 0) or 0) or None,
            "n_down": int(_num(info.get("XDJS"), 0) or 0) or None,
            "v_sh": (v_sh * 10000) if v_sh is not None else None,
            "v_ca": (v_ca * 10000) if v_ca is not None else None,
            "v_sh_zr": (v_sh_zr * 10000) if v_sh_zr is not None else None,
            "v_ca_zr": (v_ca_zr * 10000) if v_ca_zr is not None else None,
        }
    except Exception:  # noqa: BLE001
        return {}


def _qcj_row(row: dict | None) -> dict:
    """趣财经单日情绪 → 短线指标字段。"""
    if not isinstance(row, dict):
        return {}
    themes = row.get("mainThemes") or []
    if not isinstance(themes, list):
        themes = []
    themes = [str(t).strip() for t in themes if str(t).strip()]
    level = str(row.get("sentimentLevel") or "").strip() or None
    leader = str(row.get("leaderName") or "").strip() or None
    leader_top = str(row.get("leaderDayTop") or "").strip() or None
    temp = _num(row.get("temperatureDegree"))
    zt = row.get("limitUpCount")
    dt = row.get("limitDownCount")
    return {
        "qcj_temp": None if temp is None else int(temp),
        "qcj_level": level,
        "qcj_zt": int(_num(zt, 0) or 0) if zt is not None else None,
        "qcj_dt": int(_num(dt, 0) or 0) if dt is not None else None,
        "qcj_leader": leader,
        "qcj_leader_top": leader_top,
        "qcj_themes": themes or None,
        "qcj_date": str(row.get("date") or "") or None,
    }


def _fetch_qcj(as_of: str, prev: str | None) -> dict:
    """趣财经市场情绪：按场次 date 对齐 today/yesterday。

    `as_of` 必须是左侧对照所属交易日（不是日历周末）。盘前/非交易日由调用方
    先把 as_of 钉到最近一场，这里只按日期取行，不再把「序列末条」冒充日历今天。
    """
    try:
        import requests

        r = requests.get(_QCJ_MARKET, headers=_QCJ_UA, timeout=12)
        r.raise_for_status()
        raw = r.json()
        rows = (raw.get("data") or {}).get("sentiment") or []
        if not isinstance(rows, list) or not rows:
            return {}
        by_date = {
            str(row.get("date")): row
            for row in rows
            if isinstance(row, dict) and row.get("date")
        }
        out: dict[str, Any] = {}
        if as_of in by_date:
            out["today"] = _qcj_row(by_date[as_of])
        if prev and prev in by_date:
            out["yesterday"] = _qcj_row(by_date[prev])
        elif out.get("today") and rows:
            # prev 未命中时：取 as_of 在序列里的前一条（仍要求日期严格早于 as_of）
            t_date = out["today"].get("qcj_date")
            if t_date:
                for i, row in enumerate(rows):
                    if str(row.get("date")) == t_date and i > 0:
                        earlier = _qcj_row(rows[i - 1])
                        earlier_d = earlier.get("qcj_date")
                        if earlier_d and earlier_d < t_date:
                            out["yesterday"] = earlier
                        break
        return out
    except Exception:  # noqa: BLE001
        return {}


def _fetch_main_fund() -> dict:
    """主力净流入：分钟 K 取今日最新；日 K 取昨收作对比。"""
    ts = int(time.time() * 1000)
    out: dict = {}
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            raw = _em_get(
                f"https://{host}/api/qt/stock/fflow/kline/get",
                {
                    "klt": 1, "lmt": 2,
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                    "secid": "1.000001", "secid2": "0.399001", "_": ts,
                },
            )
            klines = (raw.get("data") or {}).get("klines") or []
            if klines:
                parts = str(klines[-1]).split(",")
                out["m_net"] = _num(parts[1]) if len(parts) > 1 else None
                break
        except Exception:  # noqa: BLE001
            continue

    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        try:
            raw = _em_get(
                f"https://{host}/api/qt/stock/fflow/kline/get",
                {
                    "klt": 101, "lmt": 5,
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                    "secid": "1.000001", "secid2": "0.399001", "_": ts,
                },
            )
            klines = (raw.get("data") or {}).get("klines") or []
            # 日 K：最后一根可能是今天未收盘；取倒数第二根作「昨」
            if len(klines) >= 2:
                parts = str(klines[-2]).split(",")
                out["m_net_zr"] = _num(parts[1]) if len(parts) > 1 else None
            break
        except Exception:  # noqa: BLE001
            continue
    return out


def _fetch_index_amounts() -> dict:
    """腾讯指数成交额兜底：上证 + 深证 ≈ 两市（作 A 股成交额近似）。单位元。"""
    import sys

    astock = sys.modules.get("astock")
    if astock is None:
        return {}
    try:
        parsed = astock._parse_gtimg(astock._fetch_gtimg(["sh000001", "sz399001"]))
        sh = parsed.get("000001") or {}
        sz = parsed.get("399001") or {}
        v_sh = (_num(sh.get("amount_wan")) or 0) * 10000  # 万 → 元
        v_sz = (_num(sz.get("amount_wan")) or 0) * 10000
        if v_sh <= 0 and v_sz <= 0:
            return {}
        return {
            "v_sh": v_sh if v_sh > 0 else None,
            "v_ca": (v_sh + v_sz) if (v_sh + v_sz) > 0 else None,
        }
    except Exception:  # noqa: BLE001
        return {}


def _zt_dt_fallback() -> dict:
    """实际涨跌停兜底：东财涨停/跌停池家数（与今日实时打板情绪同源）。"""
    try:
        from . import live_emotion

        snap = live_emotion.snapshot()
        if not snap.get("available"):
            return {}
        out = {}
        if snap.get("zt_count") is not None:
            out["n_sjzt"] = int(snap["zt_count"])
        if snap.get("dt_count") is not None:
            out["n_sjdt"] = int(snap["dt_count"])
        return out
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# 本地归档（供「昨日」对比）
# ---------------------------------------------------------------------------

def _archive_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _load_archive(date: str | None) -> dict:
    if not date:
        return {}
    path = _archive_path(date)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_archive(date: str, env: dict) -> None:
    """收盘窗内写入；收盘后最后一次覆盖即为「昨日」对照。失败静默。"""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        payload = {k: v for k, v in env.items() if v is not None}
        payload["date"] = date
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def _resolve_as_of(calendar_today: str) -> tuple[str, str | None, bool]:
    """锚定左侧对照场次。

    返回 (as_of, prev, is_live)：
      · as_of：左侧数字所属交易日（周末/盘前 = 最近有行情的那一场）
      · prev：as_of 的前一交易日（周末即周四，用来对照）
      · is_live：日历今天就是这场 —— 只有这时才允许写归档
    """
    qd = trade_calendar.quote_trade_day()
    latest = trade_calendar.latest_session()
    as_of = None
    if qd and qd <= calendar_today:
        as_of = qd
    elif latest and latest <= calendar_today:
        as_of = latest
    else:
        as_of = calendar_today
    prev = trade_calendar.prev_trade_date(as_of)
    # 场次与对照撞车（极端兜底失败）→ 清掉对照，避免自己比自己
    if prev and prev >= as_of:
        prev = None
    return as_of, prev, as_of == calendar_today


def _merge_today(as_of: str, prev: str | None) -> dict:
    baoer = _fetch_baoer()
    lt = _fetch_longtou()
    main = _fetch_main_fund()
    amounts = _fetch_index_amounts()
    ztdt = _zt_dt_fallback()
    qcj = _fetch_qcj(as_of, prev)

    today: dict[str, Any] = {}
    today.update(baoer)
    for k in ("n_up", "n_down"):
        if lt.get(k):
            today[k] = lt[k]
    for k in ("n_sjzt", "n_sjdt", "n_zt", "n_dt", "v_sh", "v_ca"):
        if lt.get(k) is not None:
            today[k] = lt[k]
    if today.get("n_sjzt") is None and ztdt.get("n_sjzt") is not None:
        today["n_sjzt"] = ztdt["n_sjzt"]
    if today.get("n_sjdt") is None and ztdt.get("n_sjdt") is not None:
        today["n_sjdt"] = ztdt["n_sjdt"]
    if today.get("v_sh") is None and amounts.get("v_sh") is not None:
        today["v_sh"] = amounts["v_sh"]
    if today.get("v_ca") is None and amounts.get("v_ca") is not None:
        today["v_ca"] = amounts["v_ca"]
    if main.get("m_net") is not None:
        today["m_net"] = main["m_net"]
    today.update(qcj.get("today") or {})
    today["_m_net_zr"] = main.get("m_net_zr")
    today["_v_sh_zr"] = lt.get("v_sh_zr")
    today["_v_ca_zr"] = lt.get("v_ca_zr")
    today["_qcj_yesterday"] = qcj.get("yesterday") or {}
    return today


def _build_yesterday(prev: str | None, today_raw: dict) -> dict:
    """昨日环境：本地归档为主；主力/成交额可从今日响应里的 zr 字段补；趣财经优先 API 历史。"""
    y = dict(_load_archive(prev))
    if today_raw.get("_m_net_zr") is not None and y.get("m_net") is None:
        y["m_net"] = today_raw["_m_net_zr"]
    if today_raw.get("_v_sh_zr") is not None and y.get("v_sh") is None:
        y["v_sh"] = today_raw["_v_sh_zr"]
    if today_raw.get("_v_ca_zr") is not None and y.get("v_ca") is None:
        y["v_ca"] = today_raw["_v_ca_zr"]
    qcj_y = today_raw.get("_qcj_yesterday") or {}
    for k, v in qcj_y.items():
        if v is not None:
            y[k] = v
    return y


def _strip_meta(env: dict) -> dict:
    return {k: v for k, v in env.items() if not k.startswith("_") and k != "date"}


def _archive_displayable(env: dict) -> bool:
    """归档是否足以撑起左侧对照（非实时场次优先读盘、免打上游）。"""
    return bool(
        env.get("temperature") is not None
        or env.get("n_up")
        or env.get("n_sjzt") is not None
        or env.get("m_net") is not None
        or env.get("qcj_temp") is not None
    )


def _snapshot_from_archive(
    as_of: str,
    prev: str | None,
    is_live: bool,
    today: dict,
    yesterday: dict,
) -> dict:
    available = _archive_displayable(today)
    return {
        "available": available,
        "reason": None if available else "环境指标暂不可用（归档损坏或缺失）",
        "date": as_of,
        "prev_date": prev,
        "is_live": is_live,
        "today": today,
        "yesterday": yesterday,
        "updated": china_now().strftime("%Y-%m-%d %H:%M"),
        "placeholders": {
            "volume_vs_yesterday": True,
            "volume_5d_ratio": True,
        },
        "from_archive": True,
    }


def snapshot() -> dict:
    """短线盘面环境指标。至少有一项温度/涨跌家数才算 available。

    `date` = 左侧对照场次（周末为周五），`prev_date` = 其前一交易日（周末为周四）。
    """

    calendar_today = china_now().strftime("%Y-%m-%d")
    as_of, prev, is_live = _resolve_as_of(calendar_today)
    ttl = _TTL if is_live else _OFFSESSION_TTL

    def build():
        if not is_live:
            archived = _load_archive(as_of)
            if _archive_displayable(archived):
                today = _strip_meta(archived)
                yesterday = _strip_meta(_build_yesterday(prev, {})) if prev else {}
                return _snapshot_from_archive(as_of, prev, is_live, today, yesterday)
        raw = _merge_today(as_of, prev)
        today = _strip_meta(raw)
        yesterday = _strip_meta(_build_yesterday(prev, raw)) if prev else {}
        # 只有「日历今天就是这场」且在收盘落盘窗内才写归档
        if (
            is_live
            and trade_calendar.should_write_daily_cache(as_of)
            and (
                today.get("temperature") is not None
                or today.get("n_up")
                or today.get("qcj_temp") is not None
            )
        ):
            _save_archive(as_of, today)
        available = bool(
            today.get("temperature") is not None
            or today.get("n_up")
            or today.get("n_sjzt") is not None
            or today.get("m_net") is not None
            or today.get("qcj_temp") is not None
        )
        return {
            "available": available,
            "reason": None if available else "环境指标暂不可用（各指标均未取到）",
            "date": as_of,
            "prev_date": prev,
            "is_live": is_live,
            "today": today,
            "yesterday": yesterday,
            "updated": china_now().strftime("%Y-%m-%d %H:%M"),
            "placeholders": {
                "volume_vs_yesterday": True,
                "volume_5d_ratio": True,
            },
        }

    return _cached(f"short_board:{as_of}", ttl, build) or {
        "available": False,
        "reason": "环境指标取数失败",
        "today": {},
        "yesterday": {},
        "placeholders": {"volume_vs_yesterday": True, "volume_5d_ratio": True},
    }
