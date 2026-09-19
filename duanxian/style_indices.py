"""短线风格指数：东财风格/行业板块 + 公开宽基/外围报价。

同花顺软件里那串「昨日涨停表现 / 大盘股 / 同花顺情绪指数」混了三样东西：
  · 东财也能报的风格板块（昨日涨停、大小盘、近期新高…）
  · 交易所宽基（上证、创业板、国证2000…）
  · 同花顺专有指数（全 A、情绪、热股、平均股价、短期期货恐慌）——公开源没有

本模块只输出能核到的公开报价，专有项放进 ``unavailable``，不拿打板情绪冒充。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from . import fetchers, trade_calendar
from .util import china_now

_TTL = 20.0
_OFFSESSION_TTL = 86400.0
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_ULIST_PATH = "/api/qt/ulist.np/get"
_ULIST_HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
)
_TENCENT = "http://qt.gtimg.cn/q="
_F_NAME, _F_PRICE, _F_PCT = 1, 3, 32


@dataclass(frozen=True)
class StyleItem:
    key: str
    name: str
    group: str
    code: str
    secids: tuple[str, ...]
    tencent: str = ""
    note: str = ""


GROUPS: tuple[tuple[str, str], ...] = (
    ("board", "打板风格"),
    ("size", "市值风格"),
    ("attribute", "短线属性"),
    ("growth_value", "风格类型"),
    ("dividend", "红利风格"),
    ("benchmark", "宽基指数"),
    ("finance", "金融板块"),
    ("sector", "行业指数"),
    ("external", "外围对照"),
    ("other", "其他"),
)

ITEMS: tuple[StyleItem, ...] = (
    StyleItem("yzt_yz", "昨日涨停表现", "board", "BK1050", ("90.BK1050",),
              note="东财「昨日涨停_含一字」，同花顺「昨日涨停表现」更接近这一条"),
    StyleItem("yzt", "昨日涨停", "board", "BK0815", ("90.BK0815",)),
    StyleItem("ylb_yz", "昨日连板", "board", "BK1051", ("90.BK1051",),
              note="东财「昨日连板_含一字」"),
    StyleItem("ylb", "昨日连板(不含一字)", "board", "BK0816", ("90.BK0816",)),
    StyleItem("yzb", "昨日炸板", "board", "BK1631", ("90.BK1631",)),
    StyleItem("ylb2plus", "昨日打二板以上", "board", "BK1645", ("90.BK1645",),
              note="东财「昨日打二板以上表现」，看高标隔夜有没有人接"),
    StyleItem("yzt_first", "昨日首板", "board", "BK1630", ("90.BK1630",)),
    StyleItem("yzt_touch", "昨日触板", "board", "BK0817", ("90.BK0817",)),
    StyleItem("y_high_to", "昨日高换手", "board", "BK1632", ("90.BK1632",)),
    StyleItem("y_high_amp", "昨日高振幅", "board", "BK1633", ("90.BK1633",)),
    StyleItem("large", "大盘股", "size", "BK1663", ("90.BK1663",)),
    StyleItem("mid", "中盘股", "size", "BK1664", ("90.BK1664",)),
    StyleItem("small", "小盘股", "size", "BK1643", ("90.BK1643",)),
    StyleItem("micro", "微盘股", "size", "BK1158", ("90.BK1158",)),
    StyleItem("micro_sel", "微盘精选", "size", "BK1644", ("90.BK1644",)),
    StyleItem("subnew", "次新股", "size", "BK0501", ("90.BK0501",)),
    StyleItem("st", "ST股", "size", "BK0511", ("90.BK0511",)),
    StyleItem("uncap", "近期摘帽", "size", "BK1693", ("90.BK1693",)),
    StyleItem("cyb_all", "创业板综", "size", "BK0742", ("90.BK0742",)),
    StyleItem("csi2000", "国证2000", "size", "399303", ("0.399303",), tencent="sz399303",
              note="中小盘宽基；同花顺「中小」常看这一条"),
    StyleItem("new_high", "近期新高", "attribute", "BK1674", ("90.BK1674",)),
    StyleItem("high_100d", "百日新高", "attribute", "BK1676", ("90.BK1676",)),
    StyleItem("ath", "历史新高", "attribute", "BK1675", ("90.BK1675",)),
    StyleItem("oversold", "超跌股", "attribute", "BK1671", ("90.BK1671",)),
    StyleItem("low_price", "低价股", "attribute", "BK1053", ("90.BK1053",)),
    StyleItem("hundred", "百元股", "attribute", "BK1059", ("90.BK1059",)),
    StyleItem("zhongzi", "中字头", "attribute", "BK0505", ("90.BK0505",)),
    StyleItem("em_hot", "东财热股", "attribute", "BK1637", ("90.BK1637",),
              note="公开近似，不是同花顺热股"),
    StyleItem("value_stock", "价值股", "growth_value", "BK1640", ("90.BK1640",),
              note="东财概念"),
    StyleItem("cni_growth", "国证成长", "growth_value", "399370", ("0.399370",), tencent="sz399370",
              note="官方成长风格，不是东财概念"),
    StyleItem("cni_value", "国证价值", "growth_value", "399371", ("0.399371",), tencent="sz399371",
              note="官方价值风格，不是东财概念"),
    StyleItem("csi_tech", "中证科技", "growth_value", "931186", ("2.931186",)),
    StyleItem("csi_cons", "中证消费", "growth_value", "000932", ("1.000932",), tencent="sh000932"),
    StyleItem("div_csi", "中证红利", "dividend", "000922", ("1.000922",), tencent="sh000922",
              note="东财无「高股息股 / 高股息精选」同名板块，用中证红利作公开红利风格"),
    StyleItem("div_sse", "红利指数", "dividend", "000015", ("1.000015",), tencent="sh000015"),
    StyleItem("sh", "上证指数", "benchmark", "000001", ("1.000001",), tencent="sh000001"),
    StyleItem("sz", "深证成指", "benchmark", "399001", ("0.399001",), tencent="sz399001"),
    StyleItem("cyb", "创业板指", "benchmark", "399006", ("0.399006",), tencent="sz399006"),
    StyleItem("hs300", "沪深300", "benchmark", "000300", ("1.000300",), tencent="sh000300"),
    StyleItem("star50", "科创50", "benchmark", "000688", ("1.000688",), tencent="sh000688"),
    StyleItem("bj50", "北证50", "benchmark", "899050", ("0.899050", "2.899050"), tencent="bj899050"),
    StyleItem("csi_all", "中证全指", "benchmark", "000985", ("1.000985",), tencent="sh000985",
              note="公开宽基，不是同花顺全A"),
    StyleItem("csi500", "中证500", "benchmark", "000905", ("1.000905",), tencent="sh000905"),
    StyleItem("csi1000", "中证1000", "benchmark", "000852", ("1.000852",), tencent="sh000852"),
    StyleItem("bank", "银行", "finance", "BK1283", ("90.BK1283",)),
    StyleItem("ins", "保险", "finance", "BK0474", ("90.BK0474",),
              note="东财「保险Ⅱ」"),
    StyleItem("sec", "证券", "finance", "BK0473", ("90.BK0473",),
              note="东财「证券Ⅱ」"),
    StyleItem("csi_info", "全指信息", "sector", "000993", ("1.000993",), tencent="sh000993",
              note="中证全指信息，行业指数不是宽基"),
    StyleItem("tech_lead", "科技龙头", "sector", "931087", ("2.931087",)),
    StyleItem("hsi", "恒生指数", "external", "HSI", ("100.HSI",), tencent="hkHSI"),
    StyleItem("kospi", "韩国综合指数", "external", "KS11", ("100.KS11",)),
    StyleItem("a50", "富时A50期指连续", "external", "CN00Y",
              ("100.CN00Y", "8.CN00Y", "104.CN00Y"),
              note="东财 A50 期指当月连续"),
    StyleItem("small_growth", "小盘成长", "other", "BK1667", ("90.BK1667",),
              note="东财概念，不是中证小盘成长"),
    StyleItem("small_value", "小盘价值", "other", "BK1668", ("90.BK1668",),
              note="东财概念，不是中证小盘价值"),
)

UNAVAILABLE: tuple[dict[str, str], ...] = (
    {"key": "ths_emotion", "name": "同花顺情绪指数",
     "reason": "同花顺专有指数，公开行情源没有对应报价；不要把它读成打板情绪"},
    {"key": "avg_price", "name": "A股平均股价",
     "reason": "同花顺专有统计，公开行情源没有对应报价"},
    {"key": "fut_vix", "name": "短期期货恐慌指数",
     "reason": "中国波指已停，公开源没有对应报价"},
    {"key": "high_beta", "name": "高贝塔值",
     "reason": "东财概念列表未找到同名板块"},
    {"key": "high_div", "name": "高股息股",
     "reason": "东财无同名板块；红利风格见中证红利"},
    {"key": "high_div_sel", "name": "高股息精选",
     "reason": "同花顺专有；红利风格见中证红利"},
    {"key": "ths_all_a", "name": "同花顺全A",
     "reason": "同花顺专有；宽基用中证全指作公开近似"},
    {"key": "ths_hot", "name": "同花顺热股",
     "reason": "同花顺专有；短线属性用东财热股作公开近似"},
)


def _reset_runtime_state() -> None:
    with _lock:
        _cache.clear()


def _cached(key: str, ttl: float, build):
    now = time.monotonic()
    expire_at = now + float(ttl)
    with _lock:
        hit = _cache.get(key)
        if hit and now < hit[0]:
            return hit[1]
    val = build()
    if val is not None and ttl > 0 and time.monotonic() < expire_at:
        with _lock:
            _cache[key] = (expire_at, val)
    return val


def _num(v: Any) -> Optional[float]:
    return fetchers._f(v)


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    if n is None:
        return None
    return int(n)


def _quote_from_em(row: dict) -> Optional[dict]:
    code = str(row.get("f12") or "").strip()
    pct = _num(row.get("f3"))
    if not code:
        return None
    return {
        "code": code,
        "src_name": str(row.get("f14") or ""),
        "price": _num(row.get("f2")),
        "change_pct": pct,
        "up": _int(row.get("f104")),
        "down": _int(row.get("f105")),
    }


def _ulist(secids: list[str]) -> list[dict]:
    if not secids:
        return []
    params = {
        "fltt": 2, "np": 1, "invt": 2,
        "secids": ",".join(secids),
        "fields": "f12,f13,f14,f2,f3,f104,f105",
        "_": int(time.time() * 1000),
    }
    for host in _ULIST_HOSTS:
        try:
            r = fetchers._direct_get(
                host + _ULIST_PATH, params=params,
                headers=fetchers.HEADERS, timeout=12,
            )
            data = (r.json() or {}).get("data") or {}
            diff = data.get("diff") or []
            if isinstance(diff, dict):
                diff = list(diff.values())
            if diff:
                return list(diff)
        except Exception:  # noqa: BLE001
            continue
    return []


def _tencent(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    try:
        r = fetchers._direct_get(
            _TENCENT + ",".join(symbols),
            headers=fetchers.HEADERS, timeout=12,
        )
        raw = r.content.decode("gbk", "ignore")
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for line in raw.split(";"):
        if '"' not in line or "~" not in line:
            continue
        key = line.split("=")[0].strip().split("_", 1)[-1]
        fields = line.split('"')[1].split("~")
        if len(fields) <= _F_PCT:
            continue
        pct = _num(fields[_F_PCT])
        price = _num(fields[_F_PRICE])
        if pct is None and price is None:
            continue
        out[key] = {
            "code": key,
            "src_name": fields[_F_NAME],
            "price": price,
            "change_pct": pct,
            "up": None,
            "down": None,
        }
    return out


def _clist_by_code(fs: str) -> dict[str, dict]:
    rows = fetchers._clist(fs, "f3", "f12,f14,f2,f3,f104,f105",
                           ut=fetchers.UT_FUND, pz=100, max_pages=12)
    out: dict[str, dict] = {}
    for row in rows:
        q = _quote_from_em(row)
        if q:
            out[q["code"]] = q
    return out


def _load_quotes() -> dict[str, dict]:
    """item.key → quote。缺的不进 dict。"""
    by_code: dict[str, dict] = {}
    secids: list[str] = []
    for item in ITEMS:
        secids.extend(item.secids)
    for row in _ulist(list(dict.fromkeys(secids))):
        q = _quote_from_em(row)
        if q:
            by_code[q["code"]] = q

    missing_board = [it.code for it in ITEMS if it.code.startswith("BK") and it.code not in by_code]
    if missing_board:
        boards = {}
        boards.update(_clist_by_code("m:90 t:3"))
        boards.update(_clist_by_code("m:90 t:2"))
        for code in missing_board:
            if code in boards:
                by_code[code] = boards[code]

    need_tx = [
        it.tencent for it in ITEMS
        if it.tencent and (
            it.code not in by_code or by_code[it.code].get("change_pct") is None
        )
    ]
    tx = _tencent(need_tx)
    keyed: dict[str, dict] = {}
    for item in ITEMS:
        q = by_code.get(item.code)
        if (q is None or q.get("change_pct") is None) and item.tencent:
            q = tx.get(item.tencent) or q
        if q is not None and q.get("change_pct") is not None:
            keyed[item.key] = q
    return keyed


HOTSPOT_GROUP_IDS = frozenset({
    "board", "size", "attribute", "growth_value", "dividend", "finance", "sector", "other",
})
BOARD_GROUP_KEYS = (
    "yzt_yz", "yzt", "ylb_yz", "ylb", "ylb2plus", "yzt_first", "yzb",
)
NEAR_FLAT = 0.1
MIN_BOARD_N = 4
HOTSPOT_TAKE = 5
_ITEM_ORDER = {item.key: i for i, item in enumerate(ITEMS)}


def _width_flag(pct: Optional[float], up: Optional[int], down: Optional[int]) -> Optional[str]:
    if pct is None or up is None or down is None:
        return None
    total = up + down
    if total <= 0:
        return None
    ratio = up / total
    if pct > 0 and ratio < 0.5:
        return "价升面窄"
    if pct < 0 and ratio > 0.5:
        return "价跌面宽"
    return None


def _item_view(item: StyleItem, quote: Optional[dict]) -> dict:
    q = quote or {}
    pct = q.get("change_pct")
    up = q.get("up")
    down = q.get("down")
    return {
        "key": item.key,
        "name": item.name,
        "group": item.group,
        "code": item.code,
        "change_pct": pct,
        "price": q.get("price"),
        "up": up,
        "down": down,
        "note": item.note or None,
        "available": pct is not None,
        "width_flag": _width_flag(pct, up, down),
    }


def _pct(item: Optional[dict]) -> Optional[float]:
    if not item or not item.get("available"):
        return None
    return item.get("change_pct")


def _has_breadth(item: dict) -> bool:
    up, down = item.get("up"), item.get("down")
    return up is not None and down is not None and (up + down) > 0


def _width_ok_for_hotspot(item: dict) -> bool:
    if not _has_breadth(item):
        return True
    up, down = item["up"], item["down"]
    return up / (up + down) >= 0.5


def items_by_key(packed: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in packed.get("groups") or []:
        for it in g.get("items") or []:
            out[it["key"]] = it
    return out


def rank_hotspot_candidates(by_key: dict[str, dict], csi: float) -> list[dict]:
    """风格热点候选集按超额降序、目录序稳定。宽基、外围、中证全指不参赛。"""
    candidates = [
        it for it in by_key.values()
        if it.get("available")
        and it.get("group") in HOTSPOT_GROUP_IDS
        and it["key"] != "csi_all"
    ]
    return sorted(
        candidates,
        key=lambda it: (
            -(it["change_pct"] - csi),
            _ITEM_ORDER.get(it["key"], 10**6),
        ),
    )


def packed_quotes(packed: dict) -> dict[str, dict]:
    """装配结果 → 存档用报价（涨幅、最新价、涨跌家数）。"""
    out: dict[str, dict] = {}
    for it in items_by_key(packed).values():
        if not it.get("available"):
            continue
        out[it["key"]] = {
            "change_pct": it.get("change_pct"),
            "price": it.get("price"),
            "up": it.get("up"),
            "down": it.get("down"),
        }
    return out


def _empty_rotation() -> dict:
    from . import style_rotation as sr

    return sr.empty_rotation()


def _empty_preference(status: str = "absent") -> dict:
    return {
        "status": status,
        "hotspots": [],
        "group_leads": [],
        "board_group": {"n_valid": 0, "mean": None, "vs": "不足"},
        "size_spread": {"value": None, "status": "不足"},
        "size_spread_cnindex": {"value": None},
    }


def derive_preference(packed: dict) -> dict:
    """从装配后的分组算出风格偏好。不打网络。"""
    by_key = items_by_key(packed)

    if not packed.get("available"):
        return _empty_preference("absent")

    csi = _pct(by_key.get("csi_all"))
    status = "ok" if csi is not None else "partial"

    small = _pct(by_key.get("small"))
    large = _pct(by_key.get("large"))
    if small is None or large is None:
        size_spread = {"value": None, "status": "不足"}
    else:
        size_spread = {"value": small - large, "status": "ok"}

    csi2000 = _pct(by_key.get("csi2000"))
    hs300 = _pct(by_key.get("hs300"))
    cn_spread = (
        {"value": csi2000 - hs300}
        if csi2000 is not None and hs300 is not None
        else {"value": None}
    )

    core = [by_key[k]["change_pct"] for k in BOARD_GROUP_KEYS
            if _pct(by_key.get(k)) is not None]
    n_valid = len(core)
    if n_valid < MIN_BOARD_N:
        board_group = {"n_valid": n_valid, "mean": None, "vs": "不足"}
    else:
        mean = sum(core) / n_valid
        if csi is None:
            vs = "不足"
        elif abs(mean) < NEAR_FLAT or abs(csi) < NEAR_FLAT:
            vs = "近平"
        elif (mean > 0) == (csi > 0):
            vs = "同向"
        else:
            vs = "反向"
        board_group = {"n_valid": n_valid, "mean": mean, "vs": vs}

    hotspots: list[dict] = []
    hotspot_keys: set[str] = set()
    if status == "ok" and csi is not None:
        ranked = rank_hotspot_candidates(by_key, csi)
        for it in ranked[:HOTSPOT_TAKE]:
            if not _width_ok_for_hotspot(it):
                continue
            hotspots.append({"key": it["key"], "excess": it["change_pct"] - csi})
            hotspot_keys.add(it["key"])

    group_leads = []
    for g in packed.get("groups") or []:
        gid = g.get("id")
        available = [it for it in (g.get("items") or []) if it.get("available")]
        if not available:
            continue
        lead = min(
            available,
            key=lambda it: (-it["change_pct"], _ITEM_ORDER.get(it["key"], 10**6)),
        )
        if lead["key"] not in hotspot_keys:
            group_leads.append({"group": gid, "key": lead["key"]})

    return {
        "status": status,
        "hotspots": hotspots,
        "group_leads": group_leads,
        "board_group": board_group,
        "size_spread": size_spread,
        "size_spread_cnindex": cn_spread,
    }


def assemble(quotes: dict[str, dict]) -> dict:
    """把 {key: quote} 收成页面用的分组，并挂上风格偏好。不打网络。"""
    groups = []
    hit = 0
    for gid, label in GROUPS:
        items = []
        for spec in ITEMS:
            if spec.group != gid:
                continue
            row = _item_view(spec, quotes.get(spec.key))
            if row["available"]:
                hit += 1
            items.append(row)
        groups.append({"id": gid, "label": label, "items": items})
    packed = {
        "available": hit > 0,
        "hit": hit,
        "total": len(ITEMS),
        "groups": groups,
        "unavailable": [dict(x) for x in UNAVAILABLE],
        "reason": None if hit else "风格指数取数失败",
    }
    packed["preference"] = derive_preference(packed)
    return packed


def snapshot() -> dict:
    calendar_today = china_now().strftime("%Y-%m-%d")
    # 场次不能按小时缓存：盘前 as_of 还是上一场，活过 09:15 会把凌晨快照一直当盘中用。
    as_of, prev, is_live = trade_calendar.resolve_as_of(calendar_today)
    settled = trade_calendar.is_settled(as_of)
    raw_ttl = _TTL if (is_live and not settled) else _OFFSESSION_TTL
    ttl = trade_calendar.ttl_until_session_boundary(raw_ttl)
    catalog = ",".join(i.key for i in ITEMS)

    def build():
        from . import style_rotation as sr

        try:
            quotes = _load_quotes()
        except Exception:  # noqa: BLE001
            quotes = {}
        packed = assemble(quotes)
        packed["date"] = as_of
        packed["is_live"] = is_live
        packed["updated"] = china_now().strftime("%Y-%m-%d %H:%M")
        sr.apply_to_snapshot(packed, as_of=as_of, prev=prev, settled=settled)
        return packed

    return _cached(f"snap:{as_of}:{is_live}:{settled}:{catalog}", ttl, build) or {
        "available": False,
        "reason": "风格指数取数失败",
        "date": as_of,
        "is_live": is_live,
        "hit": 0,
        "total": len(ITEMS),
        "groups": [],
        "unavailable": [dict(x) for x in UNAVAILABLE],
        "updated": china_now().strftime("%Y-%m-%d %H:%M"),
        "preference": _empty_preference("absent"),
        "rotation": _empty_rotation(),
    }
