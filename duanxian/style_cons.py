"""短线风格指数成分股：按公开源点开再取。

口径见 ``docs/inner/research/短线风格指数-成分股取数源.md``：
  · 东财 ``BK*`` → ``clist fs=b:BKxxxx``
  · 六位且非 ``399`` → 中证 ``cons.xls``
  · ``399`` 开头 → 国证 ``download-history``
  · 外围与同花顺专有项不给空列表，写明原因

不随盘 20 秒全量拉；缓存只服务点开详情。名单只描述当场篮子。
"""

from __future__ import annotations

import io
import threading
import time
from typing import Any, Optional

import pandas as pd

from . import fetchers, style_indices

_TTL = 3600.0
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_CSINDEX_CONS = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/{code}cons.xls"
)
_CNINDEX_HIST = "https://www.cnindex.com.cn/sample-detail/download-history"

_CNI_HEADERS = {**fetchers.HEADERS, "Referer": "https://www.cnindex.com.cn/"}

# 打板风格、短线属性里的东财概念每日重做成分
_DAILY_REBASKET_GROUPS = frozenset({"board", "attribute"})

_CODE_COL_HINTS = (
    "成份券代码", "成分券代码", "成份代码", "成分代码", "样本代码", "证券代码",
    "constituent code", "constituentcode", "constcode",
)
_NAME_COL_HINTS = (
    "成份券名称", "成分券名称", "成份名称", "成分名称", "样本简称", "证券名称",
    "constituent name", "constituentname", "constname",
)

_EXTERNAL_REASONS = {
    "hsi": "恒生指数没有稳定的公开股票成分接口（slist 空，常见镜像也核不到名单）。",
    "kospi": "韩国综合指数：东财/新浪均无成分，本仓库没有韩国交易所样本源。",
    "a50": "东财 CN00Y 是富时 A50 期指当月连续，不是股票指数，期指合约没有成分股列表。",
}

_ITEM_BY_KEY = {item.key: item for item in style_indices.ITEMS}
_UNAVAIL_BY_KEY = {str(u["key"]): dict(u) for u in style_indices.UNAVAILABLE}


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


def _is_jpeg(content: bytes) -> bool:
    return len(content) >= 3 and content[:3] == b"\xff\xd8\xff"


def _market_of(code: str) -> str:
    c = str(code or "").strip()
    if not c:
        return ""
    if c.startswith(("6", "9")):
        return "SH"
    if c.startswith(("0", "3")):
        return "SZ"
    if c.startswith(("4", "8")):
        return "BJ"
    return ""


def _norm_col(name: Any) -> str:
    return str(name or "").strip().replace(" ", "").replace("\u3000", "").lower()


def _is_index_meta_col(col: Any) -> bool:
    """中证 cons.xls 双语表头里的指数自身栏，不是成分栏。"""
    n = _norm_col(col)
    if "指数" in n:
        return True
    compact = n.replace("_", "")
    return "indexcode" in compact or compact.startswith("indexname")


def _col_has_code(norm: str) -> bool:
    return "代码" in norm or "code" in norm


def _col_has_name(norm: str) -> bool:
    return "简称" in norm or "名称" in norm or "name" in norm


def _col_is_constituent(norm: str) -> bool:
    return any(tok in norm for tok in ("成份", "成分", "样本", "constituent", "constcode", "constname"))


def _pick_by_hints(columns, hints: tuple[str, ...]) -> Optional[str]:
    mapped = [(_norm_col(c), c) for c in columns]
    by_norm = {n: c for n, c in mapped}
    for hint in hints:
        h = _norm_col(hint)
        if not h:
            continue
        hit = by_norm.get(h)
        if hit is not None and not _is_index_meta_col(hit):
            return hit
        for n, col in mapped:
            if h in n and not _is_index_meta_col(col):
                return col
    return None


def _pick_col(columns, hints: tuple[str, ...]) -> Optional[str]:
    hit = _pick_by_hints(columns, hints)
    if hit is not None:
        return hit
    mapped = [(_norm_col(c), c) for c in columns]
    for n, col in mapped:
        if _is_index_meta_col(col):
            continue
        if _col_is_constituent(n) and _col_has_code(n):
            return col
    for n, col in mapped:
        if _is_index_meta_col(col):
            continue
        if _col_has_code(n):
            return col
    return None


def _pick_name_col(columns) -> Optional[str]:
    hit = _pick_by_hints(columns, _NAME_COL_HINTS)
    if hit is not None:
        return hit
    mapped = [(_norm_col(c), c) for c in columns]
    for n, col in mapped:
        if _is_index_meta_col(col):
            continue
        if _col_is_constituent(n) and _col_has_name(n):
            return col
    for n, col in mapped:
        if _is_index_meta_col(col):
            continue
        if _col_has_name(n):
            return col
    return None


def _stock_code(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text in {"nan", "None"}:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit():
        text = text.zfill(6)
    return text


def _frame_to_stocks(df: pd.DataFrame) -> list[dict[str, str]]:
    if df is None or df.empty:
        return []
    work = df.copy()
    work.columns = [str(c).strip() for c in work.columns]
    code_col = _pick_col(work.columns, _CODE_COL_HINTS)
    if code_col is None:
        return []
    name_col = _pick_name_col(work.columns)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, row in work.iterrows():
        code = _stock_code(row.get(code_col))
        if not code or not code.isdigit() or code in seen:
            continue
        seen.add(code)
        name = ""
        if name_col is not None:
            name = str(row.get(name_col) or "").strip()
            if name in {"nan", "None"}:
                name = ""
        out.append({"code": code, "name": name, "market": _market_of(code)})
    return out


def _read_table_bytes(content: bytes) -> pd.DataFrame:
    if not content or _is_jpeg(content):
        raise ValueError("成分文件是图片或空响应，不是表格")
    head = content.lstrip()[:64].lower()
    if head.startswith(b"<") or b"<html" in content[:2048].lower() or b"<table" in content[:4096].lower():
        tables = pd.read_html(io.BytesIO(content))
        if not tables:
            raise ValueError("HTML 里没有表")
        return tables[0]
    bio = io.BytesIO(content)
    if content[:2] == b"PK":
        return pd.read_excel(bio, dtype=str, engine="openpyxl")
    try:
        return pd.read_excel(bio, dtype=str)
    except Exception:
        tables = pd.read_html(io.BytesIO(content))
        if not tables:
            raise
        return tables[0]


def _latest_date_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    date_col = None
    for col in df.columns:
        if "日期" in str(col) or _norm_col(col) in {"date", "tradedate"}:
            date_col = col
            break
    if date_col is None:
        return df
    series = df[date_col].astype(str).str.strip()
    latest = ""
    for val in series:
        if val and val not in {"nan", "None"} and val > latest:
            latest = val
    if not latest:
        return df
    return df.loc[series == latest]


def classify(key: str, *, code: str = "", group: str = "", reason: str = "") -> dict[str, Any]:
    """不打网络：这条风格指数用哪条成分源、能不能取。"""
    k = str(key or "").strip()
    c = str(code or "").strip()
    g = str(group or "").strip()
    unavail = _UNAVAIL_BY_KEY.get(k)
    if unavail:
        return {
            "key": k,
            "name": unavail.get("name") or k,
            "code": c,
            "group": g,
            "cons_available": False,
            "cons_source": None,
            "cons_source_label": None,
            "cons_reason": unavail.get("reason") or "公开行情源没有对应成分股。",
            "cons_note": None,
        }
    item = _ITEM_BY_KEY.get(k)
    if item is not None:
        c = c or item.code
        g = g or item.group
        name = item.name
    else:
        name = k
    note = (
        "东财概念每日重做成分，名单只说明当场样本，跨日点位不可比。"
        if g in _DAILY_REBASKET_GROUPS
        else None
    )
    if c.startswith("BK"):
        return {
            "key": k,
            "name": name,
            "code": c,
            "group": g,
            "cons_available": True,
            "cons_source": "em_bk",
            "cons_source_label": "东财板块成分",
            "cons_reason": None,
            "cons_note": note,
        }
    if len(c) == 6 and c.isdigit() and c.startswith("399"):
        return {
            "key": k,
            "name": name,
            "code": c,
            "group": g,
            "cons_available": True,
            "cons_source": "cnindex",
            "cons_source_label": "国证样本文件",
            "cons_reason": None,
            "cons_note": None,
        }
    if len(c) == 6 and c.isdigit():
        return {
            "key": k,
            "name": name,
            "code": c,
            "group": g,
            "cons_available": True,
            "cons_source": "csindex",
            "cons_source_label": "中证成分文件",
            "cons_reason": None,
            "cons_note": None,
        }
    return {
        "key": k,
        "name": name,
        "code": c,
        "group": g,
        "cons_available": False,
        "cons_source": None,
        "cons_source_label": None,
        "cons_reason": reason or _EXTERNAL_REASONS.get(k) or "没有可用的公开股票成分请求。",
        "cons_note": None,
    }


def describe(key: str) -> dict[str, Any]:
    """目录项元数据（含 UNAVAILABLE）。"""
    k = str(key or "").strip()
    item = _ITEM_BY_KEY.get(k)
    if item is not None:
        return classify(item.key, code=item.code, group=item.group)
    unavail = _UNAVAIL_BY_KEY.get(k)
    if unavail:
        return classify(k, reason=str(unavail.get("reason") or ""))
    return classify(k, reason="不是短线风格指数目录里的项。")


def _fetch_em_bk(code: str) -> list[dict[str, Any]]:
    rows = fetchers._clist(
        f"b:{code}", "f3", "f12,f14,f3",
        ut=fetchers.UT_FUND, pz=100, max_pages=40,
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        stock = _stock_code(row.get("f12"))
        if not stock or stock in seen:
            continue
        seen.add(stock)
        name = str(row.get("f14") or "").strip()
        out.append({"code": stock, "name": name, "market": _market_of(stock)})
    return out


def _download(url: str, *, params: dict | None = None, headers: dict | None = None) -> bytes:
    r = fetchers._direct_get(
        url, params=params, headers=headers or fetchers.HEADERS, timeout=30,
    )
    status = getattr(r, "status_code", 0)
    content = getattr(r, "content", b"") or b""
    ctype = ""
    try:
        ctype = str((r.headers or {}).get("Content-Type") or "")
    except Exception:  # noqa: BLE001
        ctype = ""
    if status != 200:
        raise RuntimeError(f"成分文件请求失败（HTTP {status}）")
    if _is_jpeg(content) or "image/jpeg" in ctype.lower():
        raise RuntimeError("成分文件不存在（返回了 404 图片）")
    if not content:
        raise RuntimeError("成分文件是空响应")
    return content


def _fetch_csindex(code: str) -> list[dict[str, str]]:
    content = _download(_CSINDEX_CONS.format(code=code), headers=fetchers.HEADERS)
    df = _read_table_bytes(content)
    return _frame_to_stocks(df)


def _fetch_cnindex(code: str) -> list[dict[str, str]]:
    content = _download(
        _CNINDEX_HIST,
        params={"indexcode": code},
        headers=_CNI_HEADERS,
    )
    df = _read_table_bytes(content)
    df = _latest_date_frame(df)
    return _frame_to_stocks(df)


def _empty_payload(spec: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    msg = reason or spec.get("cons_reason") or "没有可用的公开股票成分请求。"
    return {
        "key": spec["key"],
        "name": spec["name"],
        "code": spec.get("code") or "",
        "group": spec.get("group") or "",
        "available": False,
        "reason": msg,
        "source": spec.get("cons_source"),
        "source_label": spec.get("cons_source_label"),
        "note": spec.get("cons_note"),
        "count": 0,
        "stocks": [],
    }


def public_cons_usable(payload: dict[str, Any] | None) -> bool:
    """公开源名单是否可展示。中证误解析时常只剩指数自身 1 行。"""
    if not isinstance(payload, dict) or not payload.get("available"):
        return False
    stocks = payload.get("stocks") or []
    if not stocks:
        return False
    if payload.get("source") == "csindex" and len(stocks) <= 1:
        return False
    code = str(payload.get("code") or "").strip()
    if len(stocks) == 1 and code and str(stocks[0].get("code") or "") == code:
        return False
    return True


def fetch(key: str) -> dict[str, Any]:
    """点开再取成分股。不可用则带 reason，不返回空列表冒充。"""
    spec = describe(key)
    if not spec.get("cons_available"):
        return _empty_payload(spec)

    def build():
        source = spec["cons_source"]
        code = spec["code"]
        try:
            if source == "em_bk":
                stocks = _fetch_em_bk(code)
            elif source == "csindex":
                stocks = _fetch_csindex(code)
            elif source == "cnindex":
                stocks = _fetch_cnindex(code)
            else:
                return _empty_payload(spec)
        except Exception as exc:  # noqa: BLE001
            return _empty_payload(spec, reason=f"成分请求失败：{exc}")
        if not stocks:
            return _empty_payload(spec, reason="公开源没有返回成分股名单。")
        return {
            "key": spec["key"],
            "name": spec["name"],
            "code": code,
            "group": spec.get("group") or "",
            "available": True,
            "reason": None,
            "source": source,
            "source_label": spec.get("cons_source_label"),
            "note": spec.get("cons_note"),
            "count": len(stocks),
            "stocks": stocks,
        }

    return _cached(f"cons:{spec['key']}:{spec.get('code')}", _TTL, build)
