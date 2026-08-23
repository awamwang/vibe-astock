"""市场总览数据层 —— 市场情绪 + 板块资金流（板块/大盘级公开数据，不涉个股推荐）。

省流量：全站共享一份缓存（TTL 默认 5 分钟），多个用户/多次打开只抓一次；
盘中 5 分钟刷新足够，非交易时段数据本就不变。数据源全免费、无 key。
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone, timedelta

import astock
import gstock

BEIJING = timezone(timedelta(hours=8))
_CACHE: dict = {}
_TTL = 300  # 5 分钟；全站共享，省数据源压力
_OFFSESSION_TTL = 86400.0
_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/market_sentiment")
_ARCHIVE_KEYS = ("breadth", "speculation", "up", "down", "flat", "active")


def _cached(key: str, fn, valid=bool, ttl: float | None = None):
    """TTL 缓存。数据源故障的空结果不缓存（valid 判否），下次请求直接重试。"""
    effective_ttl = ttl if ttl is not None else _TTL
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < effective_ttl:
        return hit[1]
    val = fn()
    if valid(val):
        _CACHE[key] = (now, val)
    return val


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _normalize_session_date(raw: str) -> str:
    """乐咕统计日期 → YYYY-MM-DD。"""
    s = str(raw or "").strip()
    if not s:
        from duanxian.util import china_now

        return china_now().strftime("%Y-%m-%d")
    s = re.sub(r"[年月]", "-", s).replace("日", "").strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        d = digits[:8]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return s[:10]


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
    except Exception:
        return {}


def _save_archive(date: str, env: dict) -> None:
    """收盘窗内写入；收盘后最后一次覆盖即为「昨日」对照。失败静默。"""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        payload = {k: env[k] for k in _ARCHIVE_KEYS if k in env and env[k] is not None}
        payload["date"] = date
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        pass


def _yesterday_slice(prev: str | None) -> dict:
    raw = _load_archive(prev)
    return {k: raw[k] for k in _ARCHIVE_KEYS if k in raw and raw[k] is not None}


def _attach_sentiment_compare(raw: dict) -> dict:
    """为涨跌宽度类指标补上昨日对照（本地按日归档）。"""
    if not raw:
        return raw
    from duanxian import trade_calendar
    from duanxian.util import china_now

    as_of = _normalize_session_date(raw.get("date", ""))
    calendar_today = china_now().strftime("%Y-%m-%d")
    is_live = as_of == calendar_today
    slice_today = {k: raw[k] for k in _ARCHIVE_KEYS if k in raw}
    if (
        is_live
        and slice_today.get("breadth")
        and trade_calendar.should_write_daily_cache(as_of)
    ):
        _save_archive(as_of, slice_today)
    prev = trade_calendar.prev_trade_date(as_of)
    out = dict(raw)
    out["date"] = as_of
    out["prev_date"] = prev
    out["is_live"] = is_live
    out["yesterday"] = _yesterday_slice(prev)
    return out


def _sentiment_raw() -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机（客观数据机械分档）。"""
    from duanxian import trade_calendar

    if not trade_calendar.is_calendar_session_live():
        as_of = trade_calendar.latest_session()
        if as_of:
            archived = _load_archive(as_of)
            if archived.get("breadth"):
                raw = {k: archived[k] for k in _ARCHIVE_KEYS if k in archived}
                raw["date"] = as_of
                return raw
    try:
        # akshare 惰性导入（同 astock 模式）：未装时降级返回空，不挡整个服务启动
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return {}
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _sentiment() -> dict:
    return _attach_sentiment_compare(_sentiment_raw())


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。不含领涨股等个股字段。"""
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        f = f.sort_values("净额", ascending=False)
    except Exception:
        return []
    out = []
    for _, row in f.iterrows():
        out.append({
            "name": str(row["行业"]),
            "pct": round(float(row.get("行业-涨跌幅", 0) or 0), 2),
            "net": round(float(row.get("净额", 0) or 0), 2),
            "inflow": round(float(row.get("流入资金", 0) or 0), 2),
            "outflow": round(float(row.get("流出资金", 0) or 0), 2),
            "firms": _num(row.get("公司家数")),
        })
    return out


def get_overview() -> dict:
    """市场情绪 + 板块资金（含缓存）。资金轮动由前端从 sectors 头尾取。"""
    from duanxian import trade_calendar

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    key = "overview:live" if live else f"overview:off:{trade_calendar.latest_session() or 'na'}"

    def build():
        return {
            "sentiment": _sentiment(),
            "sectors": _sectors(),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached(key, build, valid=lambda v: bool(v.get("sentiment") or v.get("sectors")), ttl=ttl)


def _emotion() -> dict:
    """短线情绪（聚合口径，**零个股名**）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    数据源＝东财涨停板四池（push2ex）。只把池子聚合成计数与比率，
    **不输出任何个股 code/name**——守产品「零标的」红线（个股清单是甩名单，不做）。
    """
    # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）。
    today = datetime.now(BEIJING).date()
    resolved, zt = "", []
    for back in range(8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
        if zt:
            resolved = d
            break
    if not resolved:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）。
    # 产品定位调整（2026-07-05）：从「零标的」→「展示客观榜单但不推荐/不预测/不评分」。
    # 涨停原因题材串（问财，与首板页共用缓存；缺 key/失败 → 空串，不影响主数据）。
    try:
        import firstboard  # 函数内导入：firstboard 顶部 import market，避免循环依赖

        reasons, _reason_err = firstboard.get_reasons(resolved)
    except Exception:  # noqa: BLE001
        reasons = {}
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),      # 成交额,元（'-' 占位归一为 None，防排序对 str 取负崩溃）
            "float_cap": astock._numf(p.get("ltsz")),     # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
            "reason": reasons.get(str(p.get("c", "")), ""),  # 涨停原因题材串
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        "zt_count": zt_count,
        "dt_count": len(dt),
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
    }


def get_short_term_emotion() -> dict:
    """短线情绪（含缓存，5 分钟）。"""
    from duanxian import trade_calendar

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    key = "emotion:live" if live else f"emotion:off:{trade_calendar.latest_session() or 'na'}"
    return _cached(key, _emotion, ttl=ttl)


def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（客观公开榜单，含缓存 5 分钟）。"""
    from duanxian import trade_calendar

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    key = "turnover_top:live" if live else f"turnover_top:off:{trade_calendar.latest_session() or 'na'}"

    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached(key, build, valid=lambda v: bool(v.get("stocks")), ttl=ttl)


def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，含缓存 5 分钟）。空结果不缓存。"""
    return _cached("global_indices", gstock.global_indices, valid=bool)
