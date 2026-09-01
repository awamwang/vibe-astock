"""A 股全量静态列表 —— 统一获取、内存缓存、多源降级。

启动时按配置优先级依次尝试各数据源，首个成功即载入内存。
列表项仅含静态字段（code / name / market / types），不含行情等动态信息。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal

import astock
from profile_paths import agents_dir

logger = logging.getLogger(__name__)

SourceId = Literal["eastmoney", "akshare"]
MarketId = Literal["SH", "SZ", "BJ"]

# 沪深京全 A（与 duanxian/fetchers.ALL_A_FS 对齐）
A_SHARE_FS = (
    "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:7,m:1+t:3,"
    "m:0+t:13,m:1+t:81+s:2048"
)

_DEFAULT_SOURCES: tuple[SourceId, ...] = ("eastmoney", "akshare")
_CACHE_SCHEMA = 1
_CACHE_DIR = str(agents_dir() / "cache")
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com")

_NEW_DAYS = 30
_SUBNEW_DAYS = 365


@dataclass(frozen=True)
class StockItem:
    """A 股静态列表项。"""

    code: str
    name: str
    market: MarketId
    types: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "market": self.market,
            "types": list(self.types),
        }


@dataclass
class LoadMeta:
    ok: bool
    source: SourceId | Literal["cache"] | None = None
    count: int = 0
    tried: tuple[str, ...] = ()
    error: str | None = None
    updated_at: str | None = None
    from_cache: bool = False


_by_code: dict[str, StockItem] = {}
_name_to_code: dict[str, str] = {}
_loaded = False
_meta = LoadMeta(ok=False)
_cache_updated_at: str | None = None
_REFRESH_LOCK = threading.Lock()
_REFRESH_RUNNING = False


def configured_sources() -> tuple[SourceId, ...]:
    """读取 STOCK_LIST_SOURCES，逗号分隔，无效项忽略。"""
    raw = os.environ.get("STOCK_LIST_SOURCES", "").strip()
    if not raw:
        return _DEFAULT_SOURCES
    valid = {"eastmoney", "akshare"}
    out: list[SourceId] = []
    for part in raw.split(","):
        sid = part.strip().lower()
        if sid in valid and sid not in out:
            out.append(sid)  # type: ignore[arg-type]
    return tuple(out) if out else _DEFAULT_SOURCES


def read_source_order() -> tuple[str, ...]:
    """读取优先级：本地缓存 → 网络源（按 STOCK_LIST_SOURCES）。"""
    return ("cache", *configured_sources())


def _cache_path() -> str:
    return os.path.join(_CACHE_DIR, "stock_universe.json")


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _items_from_payload(rows: list[dict[str, Any]]) -> list[StockItem]:
    out: list[StockItem] = []
    for row in rows:
        code = str(row.get("code") or "").zfill(6)
        name = str(row.get("name") or "").strip()
        market = row.get("market") or infer_market(code)
        if market not in ("SH", "SZ", "BJ"):
            market = infer_market(code)
        types_raw = row.get("types") or ()
        if isinstance(types_raw, str):
            types = (types_raw,) if types_raw else ()
        else:
            types = tuple(str(x) for x in types_raw if x)
        item = StockItem(code=code, name=name, market=market, types=types)  # type: ignore[arg-type]
        if code.isdigit() and len(code) == 6 and name:
            out.append(item)
    return out


def _save_cache(items: list[StockItem], source: SourceId) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    updated_at = _now_str()
    payload = {
        "schema": _CACHE_SCHEMA,
        "updated_at": updated_at,
        "source": source,
        "count": len(items),
        "items": [it.to_dict() for it in items],
    }
    path = _cache_path()
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return updated_at


def _load_cache_file() -> tuple[list[StockItem], str, SourceId] | None:
    path = _cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("schema") or 0) != _CACHE_SCHEMA:
        return None
    source = str(data.get("source") or "eastmoney").lower()
    if source not in ("eastmoney", "akshare"):
        source = "eastmoney"
    items = _items_from_payload(list(data.get("items") or []))
    if not items:
        return None
    updated_at = str(data.get("updated_at") or "").strip() or None
    return items, updated_at or _now_str(), source  # type: ignore[return-value]


def infer_market(code: str) -> MarketId:
    """6 位代码 → 交易所。"""
    c = str(code).zfill(6)
    if c.startswith(("4", "8")):
        return "BJ"
    if c.startswith(("6", "5", "9")):
        return "SH"
    return "SZ"


def _is_st(name: str) -> bool:
    n = (name or "").strip().upper()
    return bool(re.match(r"^(\*?ST|S\*?ST|SST)", n))


def _parse_list_date(raw: Any) -> date | None:
    if raw is None or raw in ("", "-", "None", "nan"):
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, (int, float)) and raw > 0:
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).date()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _board_from_hint(board_hint: str | None, code: str) -> str:
    hint = (board_hint or "").strip()
    if "科创" in hint:
        return "科创板"
    if "创业" in hint:
        return "创业板"
    if "北交" in hint:
        return "北交所"
    c = code.zfill(6)
    if c.startswith(("688", "689")):
        return "科创板"
    if c.startswith(("300", "301")):
        return "创业板"
    if c.startswith(("4", "8")):
        return "北交所"
    return "主板"


def build_types(
    code: str,
    name: str,
    *,
    board_hint: str | None = None,
    list_date: date | None = None,
    today: date | None = None,
) -> tuple[str, ...]:
    """推断板块与 ST / 新股 / 次新股标签。"""
    tags: list[str] = []
    tags.append(_board_from_hint(board_hint, code))
    if _is_st(name):
        tags.append("ST")
    ref = today or date.today()
    if list_date:
        days = (ref - list_date).days
        if days >= 0:
            if days <= _NEW_DAYS:
                tags.append("新股")
            elif days <= _SUBNEW_DAYS:
                tags.append("次新股")
    return tuple(tags)


def _item(
    code: str,
    name: str,
    *,
    board_hint: str | None = None,
    list_date: date | None = None,
    today: date | None = None,
) -> StockItem | None:
    code = str(code).strip().zfill(6)
    name = str(name).strip()
    if not code.isdigit() or len(code) != 6 or not name:
        return None
    return StockItem(
        code=code,
        name=name,
        market=infer_market(code),
        types=build_types(code, name, board_hint=board_hint, list_date=list_date, today=today),
    )


def _fetch_eastmoney(*, today: date | None = None) -> list[StockItem]:
    """东财 clist 分页拉全 A，字段 f12/f14/f26（上市日）。"""
    rows: list[dict] = []
    page = 1
    total = None
    while page <= 80:
        params = {
            "pn": page,
            "pz": 100,
            "po": 1,
            "np": 1,
            "ut": _EM_UT,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": A_SHARE_FS,
            "fields": "f12,f14,f26",
        }
        data = None
        for host in _EM_HOSTS:
            try:
                r = astock.em_get(
                    f"https://{host}/api/qt/clist/get",
                    params=params,
                    headers={"User-Agent": astock.UA},
                    timeout=15,
                )
                data = r.json().get("data")
                if data and data.get("diff"):
                    break
            except Exception:
                continue
        if not data or not data.get("diff"):
            break
        diff = data["diff"]
        rows.extend(diff)
        total = data.get("total") or total
        if total and len(rows) >= total:
            break
        if len(diff) == 0:
            break
        page += 1
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("东财 clist 未返回任何股票")
    out: list[StockItem] = []
    seen: set[str] = set()
    for row in rows:
        item = _item(
            row.get("f12", ""),
            row.get("f14", ""),
            list_date=_parse_list_date(row.get("f26")),
            today=today,
        )
        if item and item.code not in seen:
            seen.add(item.code)
            out.append(item)
    if not out:
        raise RuntimeError("东财 clist 解析后无有效股票")
    return out


def _fetch_akshare(*, today: date | None = None) -> list[StockItem]:
    """AkShare 交易所官网名单（含板块/上市日）。"""
    import akshare as ak

    out: list[StockItem] = []
    seen: set[str] = set()

    def _add(code: Any, name: Any, *, board_hint: str | None, list_date: Any) -> None:
        item = _item(
            code,
            name,
            board_hint=board_hint,
            list_date=_parse_list_date(list_date),
            today=today,
        )
        if item and item.code not in seen:
            seen.add(item.code)
            out.append(item)

    df_sz = ak.stock_info_sz_name_code(symbol="A股列表")
    for _, row in df_sz.iterrows():
        _add(row.get("A股代码"), row.get("A股简称"), board_hint=str(row.get("板块", "")), list_date=row.get("A股上市日期"))

    df_sh = ak.stock_info_sh_name_code(symbol="主板A股")
    for _, row in df_sh.iterrows():
        _add(row.get("证券代码"), row.get("证券简称"), board_hint="主板", list_date=row.get("上市日期"))

    df_kcb = ak.stock_info_sh_name_code(symbol="科创板")
    for _, row in df_kcb.iterrows():
        _add(row.get("证券代码"), row.get("证券简称"), board_hint="科创板", list_date=row.get("上市日期"))

    df_bj = ak.stock_info_bj_name_code()
    for _, row in df_bj.iterrows():
        _add(row.get("证券代码"), row.get("证券简称"), board_hint="北交所", list_date=row.get("上市日期"))

    if not out:
        raise RuntimeError("AkShare 交易所名单解析后无有效股票")
    return out


_FETCHERS: dict[SourceId, Callable[..., list[StockItem]]] = {
    "eastmoney": _fetch_eastmoney,
    "akshare": _fetch_akshare,
}


def _apply_items(
    items: list[StockItem],
    source: SourceId | Literal["cache"],
    *,
    tried: tuple[str, ...] = (),
    updated_at: str | None = None,
    from_cache: bool = False,
) -> None:
    global _by_code, _name_to_code, _loaded, _meta, _cache_updated_at
    _by_code = {it.code: it for it in items}
    _name_to_code = {it.name: it.code for it in items}
    _loaded = True
    if updated_at:
        _cache_updated_at = updated_at
    _meta = LoadMeta(
        ok=True,
        source=source,
        count=len(items),
        tried=tried or (source,),
        updated_at=updated_at or _cache_updated_at,
        from_cache=from_cache,
    )


def load_from_cache() -> LoadMeta:
    """仅从用户目录本地缓存载入，不打网络。"""
    global _loaded, _meta, _cache_updated_at
    hit = _load_cache_file()
    if hit is None:
        _loaded = False
        _meta = LoadMeta(
            ok=False,
            tried=("cache",),
            error="本地无股票列表缓存",
        )
        return _meta
    items, updated_at, source = hit
    _apply_items(
        items,
        "cache",
        tried=("cache",),
        updated_at=updated_at,
        from_cache=True,
    )
    logger.info("股票列表已从本地缓存载入：%d 只（原数据源=%s）", len(items), source)
    return _meta


def _fetch_from_network() -> LoadMeta:
    """按配置优先级从网络拉取，成功则写入本地缓存。"""
    global _loaded, _meta
    sources = configured_sources()
    tried: list[SourceId] = []
    errors: list[str] = []
    today = date.today()
    for sid in sources:
        tried.append(sid)
        fetcher = _FETCHERS.get(sid)
        if not fetcher:
            continue
        try:
            items = fetcher(today=today)
            updated_at = _save_cache(items, sid)
            _apply_items(
                items,
                sid,
                tried=tuple(tried),
                updated_at=updated_at,
                from_cache=False,
            )
            logger.info("股票列表已刷新：%d 只，数据源=%s", len(items), sid)
            return _meta
        except Exception as exc:  # noqa: BLE001
            msg = f"{sid}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            logger.warning("股票列表源失败，尝试下一源：%s", msg)
    _loaded = False
    _meta = LoadMeta(
        ok=False,
        tried=tuple(tried),
        error="；".join(errors) if errors else "无可用数据源",
    )
    return _meta


def load_stock_universe(*, force: bool = False) -> LoadMeta:
    """载入股票列表：默认只读本地缓存；force=True 时走网络刷新。"""
    if _loaded and not force:
        return _meta
    if force:
        return _fetch_from_network()
    return load_from_cache()


def refresh_universe(*, blocking: bool = True) -> LoadMeta:
    """从网络刷新股票列表并写入本地缓存。"""
    if blocking:
        return _fetch_from_network()
    return schedule_refresh()


def is_refreshing() -> bool:
    return _REFRESH_RUNNING


def schedule_refresh() -> LoadMeta:
    """后台从网络刷新；已在刷新中则直接返回当前状态。"""
    global _REFRESH_RUNNING
    if _REFRESH_RUNNING:
        return _meta
    with _REFRESH_LOCK:
        if _REFRESH_RUNNING:
            return _meta
        _REFRESH_RUNNING = True

    def _run() -> None:
        global _REFRESH_RUNNING
        try:
            meta = _fetch_from_network()
            if meta.ok:
                print(f"✓ 股票列表已刷新 {meta.count} 只（{meta.source}）")
            else:
                print(f"⚠ 股票列表刷新失败：{meta.error}")
        finally:
            with _REFRESH_LOCK:
                _REFRESH_RUNNING = False

    threading.Thread(target=_run, daemon=True, name="stock-universe-refresh").start()
    return _meta


def ensure_loaded() -> LoadMeta:
    """惰性加载（供非启动路径调用）。"""
    return load_stock_universe(force=False)


def get_load_meta() -> LoadMeta:
    return _meta


def is_loaded() -> bool:
    return _loaded


def get_stock_list() -> list[StockItem]:
    """返回全量列表副本；未加载时尝试惰性加载。"""
    if not _loaded:
        ensure_loaded()
    return list(_by_code.values())


def get_stock_by_code(code: str) -> StockItem | None:
    if not _loaded:
        ensure_loaded()
    return _by_code.get(str(code).strip().zfill(6))


def get_name_to_code() -> dict[str, str]:
    if not _loaded:
        ensure_loaded()
    return dict(_name_to_code)


def get_code_to_name() -> dict[str, str]:
    if not _loaded:
        ensure_loaded()
    return {code: it.name for code, it in _by_code.items()}


def resolve_code_by_name(name: str) -> str | None:
    """名称 → 代码；精确匹配，去括号后再试。"""
    if not _loaded:
        ensure_loaded()
    n = (name or "").strip()
    if not n:
        return None
    if n in _name_to_code:
        return _name_to_code[n]
    base = n.split("（")[0].split("(")[0].strip()
    return _name_to_code.get(base)


def startup_load() -> LoadMeta:
    """进程启动时只读本地缓存，失败不抛异常、不自动打网络。"""
    meta = load_from_cache()
    if meta.ok:
        print(f"✓ 股票列表 {meta.count} 只（本地缓存）")
    else:
        print(f"ℹ 股票列表：{meta.error}，可在「数据备份」页手动刷新")
    return meta


def export_status() -> dict[str, Any]:
    """供 API 返回的当前状态。"""
    order = read_source_order()
    labels = {
        "cache": "本地缓存",
        "eastmoney": "东财",
        "akshare": "AkShare",
    }
    return {
        "loaded": _loaded,
        "refreshing": _REFRESH_RUNNING,
        "count": _meta.count if _loaded else 0,
        "source": _meta.source,
        "from_cache": _meta.from_cache,
        "updated_at": _meta.updated_at or _cache_updated_at,
        "cache_path": _cache_path(),
        "cache_exists": os.path.isfile(_cache_path()),
        "read_order": [{"id": sid, "label": labels.get(sid, sid)} for sid in order],
        "network_sources": list(configured_sources()),
        "error": None if _loaded else _meta.error,
    }
