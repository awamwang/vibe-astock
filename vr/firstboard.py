"""首板分析数据层 —— 今日首板涨停股（连板数=1）+ 涨停原因题材串。

短线投资实例专属模块（不回推开源仓库）。
- 首板名单：东财涨停池（astock.em_zt_topic_pool，免费无 key）。
- 涨停原因：优先读题材树落盘缓存（含首板页导入的同花顺 txt）；没有再问同花顺问财
  （需要 IWENCAI_API_KEY）。拿不到时优雅降级为空串，页面照常显示其余字段。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import astock
from market import BEIJING, _num

_CACHE: dict = {}
_TTL = 600  # 10 分钟；涨停原因盘中变化不快
_ZT_REASONS_DIR = os.path.expanduser("~/.duanxian-agents/cache/zt_reasons")


def _clean_reason(text: str, max_tags: int = 4, max_len: int = 40) -> str:
    """题材串清洗：统一分隔符、限标签数与总长（问财多用 '+' 分隔）。"""
    text = text.replace("，", "+").replace(",", "+").strip()
    tags = [t.strip() for t in text.split("+") if t.strip()]
    out = "+".join(tags[:max_tags])
    return out[:max_len]


def _fetch_reasons(date: str) -> tuple[dict, str | None]:
    """问财拉当日涨停原因，返回 ({6位代码: 题材串}, 错误说明或 None)。"""
    if not os.environ.get("IWENCAI_API_KEY"):
        return {}, "未配置 IWENCAI_API_KEY，涨停原因暂缺"
    try:
        from iwencai_client import IwencaiClient

        client = IwencaiClient()
    except Exception as e:  # noqa: BLE001
        return {}, f"问财客户端初始化失败：{type(e).__name__}"

    reasons: dict[str, str] = {}
    try:
        for page in range(1, 4):  # 单页 50，涨停一般 1~3 页
            df = client.query("今日涨停的股票 涨停原因", page=page, limit=50)
            if df is None or len(df) == 0:
                break
            code_cols = [c for c in df.columns if "代码" in c]
            reason_cols = [c for c in df.columns if "涨停原因" in c]
            if not code_cols or not reason_cols:
                return reasons, "问财返回缺少涨停原因列"
            cc, rc = code_cols[0], reason_cols[0]
            for _, row in df.iterrows():
                code6 = str(row[cc])[:6]
                reason = str(row[rc]).strip()
                if reason and reason.lower() != "nan" and code6 not in reasons:
                    reasons[code6] = _clean_reason(reason)
            if len(df) < 50:
                break
    except Exception as e:  # noqa: BLE001
        return reasons, f"问财查询异常：{type(e).__name__}"
    return reasons, None


_REASONS_CACHE: dict = {}


def _read_disk_reasons(date: str) -> dict:
    """读题材事件树同一份落盘缓存（手工导入的涨停原因也写在这儿）。"""
    ymd = str(date).replace("-", "")
    if len(ymd) != 8 or not ymd.isdigit():
        return {}
    iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    path = os.path.join(_ZT_REASONS_DIR, f"{iso}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        if env.get("date") not in (iso, ymd):
            return {}
        reasons = env.get("reasons") or {}
        return {str(k).zfill(6): str(v) for k, v in reasons.items() if v}
    except Exception:  # noqa: BLE001
        return {}


def apply_imported_reasons(date: str, reasons: dict) -> None:
    """导入成功后灌进内存缓存，并让首板列表 / 短线情绪下次重建。"""
    ymd = str(date).replace("-", "")
    _CACHE.pop("first_board", None)
    try:
        import market as _market

        _market._CACHE.pop("emotion", None)
    except Exception:  # noqa: BLE001
        pass
    _REASONS_CACHE[ymd] = (time.time(), dict(reasons), None)


def get_reasons(date: str) -> tuple[dict, str | None]:
    """当日全部涨停股的涨停原因（带缓存，首板页与每日复盘连板表共用）。"""
    hit = _REASONS_CACHE.get(date)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1], hit[2]
    disk = _read_disk_reasons(date)
    if disk:
        _REASONS_CACHE[date] = (time.time(), disk, None)
        return disk, None
    reasons, err = _fetch_reasons(date)
    if reasons:
        _REASONS_CACHE[date] = (time.time(), reasons, err)
    return reasons, err


def _hhmm(v) -> str:
    """池内时间字段（HHMMSS 整数）→ 'HH:MM'。"""
    s = str(_num(v)).zfill(6)
    return f"{s[:2]}:{s[2:4]}" if len(s) == 6 else ""


def _first_board() -> dict:
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

    reasons, reason_note = get_reasons(resolved)

    stocks = [
        {
            "code": str(p.get("c", "")),
            "name": p.get("n", ""),
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),
            "float_cap": astock._numf(p.get("ltsz")),
            "industry": p.get("hybk", ""),
            "seal_time": _hhmm(p.get("fbt")),
            "break_count": _num(p.get("zbc")),
            "reason": reasons.get(str(p.get("c", "")), ""),
        }
        for p in zt
        if (_num(p.get("lbc")) or 1) == 1
    ]  # 池接口 sort=fbt:asc，天然按首封时间升序（早封在前）

    return {
        "date": resolved,
        "total_zt": len(zt),
        "first_count": len(stocks),
        "reason_note": reason_note,
        "stocks": stocks,
    }


def get_first_board() -> dict:
    """首板列表（TTL 缓存；空结果不缓存，下次直接重试）。"""
    now = time.time()
    hit = _CACHE.get("first_board")
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = _first_board()
    if val:
        _CACHE["first_board"] = (now, val)
    return val
