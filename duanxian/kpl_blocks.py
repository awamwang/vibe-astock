"""开盘啦板块目录 —— 分页拉取 + 按日落盘，每日自动最多一次。

数据源：``RealRankingInfo``（与 mood_block 同站）。
  · ZSType=4 行业 · 5 概念 · 6 地域 · 7 人气综合

自动 ``ensure``：若当日已有落盘则复用；``force=True``（手动刷新）才强制重拉。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from . import paths as _paths
from .util import china_now, china_today

_PAGE_SIZE = 30
_MAX_PAGES = 40
_LOCK = threading.Lock()
_mem: dict[str, Any] | None = None
_CACHE_DIR = ""

_LONGTOU_HQ = "https://apphq.longhuvip.com/w1/api/index.php"
_UA = {
    "User-Agent": "lhb/5.13.7 (com.kaipanla.www; build:0; iOS 16.1.0) Alamofire/4.9.1",
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}

# ZSType → (kind, label)；人气榜优先写入名称索引（PlateID 供点查）
_ZS_KINDS: tuple[tuple[int, str, str], ...] = (
    (7, "hot", "人气"),
    (5, "concept", "概念"),
    (4, "industry", "行业"),
    (6, "region", "地域"),
)

# 与同花顺 kind 对齐的开盘啦结构类型
THS_TO_KPL_KIND = {
    "conception": "concept",
    "industry": "industry",
    "region": "region",
}


@_paths.register_rebind
def _rebind_paths() -> None:
    global _CACHE_DIR
    _CACHE_DIR = str(_paths.agents_dir() / "cache" / "kpl_blocks")


def _now() -> str:
    return china_now().strftime("%Y-%m-%d %H:%M:%S")


def _archive_path(date: str) -> str:
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _http_get_json(url: str) -> Any:
    import requests

    r = requests.get(url, headers=_UA, timeout=15)
    r.raise_for_status()
    return r.json()


def _num(v, default=None):
    try:
        if v in ("-", "", None):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_row(item: Any, *, kind: str, kind_label: str, sort: int) -> Optional[dict]:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None
    code = str(item[0]).strip() if item[0] is not None else ""
    name = str(item[1]).strip() if item[1] is not None else ""
    if not code or not name:
        return None
    power = _num(item[2]) if len(item) > 2 else None
    pct = _num(item[3]) if len(item) > 3 else None
    speed = _num(item[4]) if len(item) > 4 else None
    m_net = _num(item[6]) if len(item) > 6 else None
    return {
        "kind": kind,
        "kind_label": kind_label,
        "code": code,
        "name": name,
        "power": int(power) if power is not None else None,
        "pct": pct,
        "speed": speed,
        "m_net": m_net,
        "sort": sort,
        "node_type": "flat",
        "tree_path": name,
    }


def _fetch_zs_type(zs: int, kind: str, kind_label: str) -> tuple[list[dict], Optional[int], list[str]]:
    """分页拉某一 ZSType；返回 (rows, api_count, errors)。"""
    rows: list[dict] = []
    seen: set[str] = set()
    api_count: Optional[int] = None
    errors: list[str] = []
    try:
        for page in range(_MAX_PAGES):
            index = page * _PAGE_SIZE
            url = (
                f"{_LONGTOU_HQ}?Order=1&a=RealRankingInfo&st={_PAGE_SIZE}"
                f"&apiv=w25&Type=1&c=ZhiShuRanking&PhoneOSNew=1"
                f"&Index={index}&ZSType={zs}&"
            )
            raw = _http_get_json(url)
            if api_count is None:
                try:
                    api_count = int(raw.get("Count")) if raw.get("Count") is not None else None
                except (TypeError, ValueError):
                    api_count = None
            batch = raw.get("list") or []
            if not batch:
                break
            for i, item in enumerate(batch):
                parsed = _parse_row(item, kind=kind, kind_label=kind_label, sort=index + i + 1)
                if not parsed or parsed["code"] in seen:
                    continue
                seen.add(parsed["code"])
                rows.append(parsed)
            if len(batch) < _PAGE_SIZE:
                break
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{kind}: {type(exc).__name__}: {exc}")
    return rows, api_count, errors


def _fetch_all() -> dict[str, Any]:
    kinds: dict[str, Any] = {}
    errors: list[str] = []
    for zs, kind, label in _ZS_KINDS:
        rows, api_count, errs = _fetch_zs_type(zs, kind, label)
        errors.extend(errs)
        kinds[kind] = {
            "kind": kind,
            "kind_label": label,
            "zs_type": zs,
            "count": len(rows),
            "api_count": api_count,
            "rows": rows,
        }
    return {
        "updated_at": _now(),
        "fetched_date": china_today(),
        "kinds": kinds,
        "errors": errors,
        "from_cache": False,
        "available": any(int((k.get("count") or 0)) > 0 for k in kinds.values()),
    }


def _load_archive(date: str) -> dict[str, Any] | None:
    path = _archive_path(date)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        kinds = data.get("kinds")
        if not isinstance(kinds, dict) or not kinds:
            return None
        data = dict(data)
        data["from_cache"] = True
        data["fetched_date"] = str(data.get("fetched_date") or date)
        return data
    except Exception:  # noqa: BLE001
        return None


def _save_archive(payload: dict[str, Any]) -> None:
    date = str(payload.get("fetched_date") or china_today())
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _archive_path(date)
        tmp = f"{path}.{os.getpid()}.tmp"
        body = {k: v for k, v in payload.items() if v is not None}
        body["fetched_date"] = date
        body["from_cache"] = False
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass


def _empty(reason: str = "") -> dict[str, Any]:
    return {
        "updated_at": None,
        "fetched_date": None,
        "kinds": {},
        "errors": [reason] if reason else [],
        "from_cache": False,
        "available": False,
        "empty": True,
    }


def get_snapshot() -> dict[str, Any]:
    """内存快照；若空则尝试读当日落盘（不触发网络）。"""
    global _mem
    with _LOCK:
        if _mem:
            return dict(_mem)
    archived = _load_archive(china_today())
    if archived:
        with _LOCK:
            _mem = archived
        return dict(archived)
    return _empty()


def ensure(*, force: bool = False) -> dict[str, Any]:
    """确保开盘啦目录就绪。

    ``force=False``：当日已有落盘/内存则直接返回；否则拉网并落盘。
    ``force=True``：强制重拉并覆盖当日落盘。
    """
    global _mem
    today = china_today()
    if not force:
        with _LOCK:
            if _mem and str(_mem.get("fetched_date") or "") == today and _mem.get("available"):
                out = dict(_mem)
                out["from_cache"] = True
                return out
        archived = _load_archive(today)
        if archived and archived.get("available"):
            with _LOCK:
                _mem = archived
            return dict(archived)

    payload = _fetch_all()
    if payload.get("available"):
        _save_archive(payload)
    with _LOCK:
        _mem = payload
    return dict(payload)


def refresh() -> dict[str, Any]:
    """手动刷新（忽略日限）。"""
    return ensure(force=True)


def all_rows(snap: dict[str, Any] | None = None) -> list[dict]:
    """展平各类型行。"""
    data = snap if snap is not None else get_snapshot()
    out: list[dict] = []
    for _zs, kind, _label in _ZS_KINDS:
        entry = (data.get("kinds") or {}).get(kind) or {}
        rows = entry.get("rows") or []
        if isinstance(rows, list):
            out.extend(rows)
    return out


def build_name_index(snap: dict[str, Any] | None = None):
    """名称 → 开盘啦行；同名时优先人气榜 PlateID。"""
    from . import block_dialect as dialect  # noqa: PLC0415

    data = snap if snap is not None else get_snapshot()
    idx = dialect.build_kpl_index()
    # _ZS_KINDS 已按人气优先排列；后写入不覆盖 by_name
    for row in all_rows(data):
        idx.add(
            str(row.get("code") or ""),
            str(row.get("name") or ""),
            kind=row.get("kind"),
            kind_label=row.get("kind_label"),
            power=row.get("power"),
            pct=row.get("pct"),
            speed=row.get("speed"),
            m_net=row.get("m_net"),
        )
    return idx
