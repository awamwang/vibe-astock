"""短线盘面 · 重点板块跟踪（昨今对比）。

跟踪集合：
  · 昨日人气定稿榜中人气 > 5000 的板块（标签「人气」）
  · 消息关注板块配置（标签「收藏」）；经 ``block_dialect`` 映射到开盘啦 PlateID

指标：优先 ``GetPlate_Info_QJ`` 指定板块点查；昨日榜内已有字段则复用，避免重复请求。
昨日人气榜只拉一次定稿（``mood_block.ranking_for_date``，可落盘）。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import block_dialect as dialect
from . import message_follow_blocks as mfb
from . import mood_block as mb
from . import trade_calendar
from .util import china_now

_HOT_POWER = 5000
_TTL = 20.0
_OFFSESSION_TTL = 86400.0
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

_TAG_HOT = "hot"
_TAG_FOLLOW = "follow"
_TAG_LABELS = {_TAG_HOT: "人气", _TAG_FOLLOW: "收藏"}


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


def _metrics_from_rank_row(row: dict | None) -> dict[str, Any]:
    if not row:
        return {
            "power": None,
            "pct": None,
            "m_net": None,
            "amount": None,
            "zt": None,
            "sort": None,
        }
    return {
        "power": row.get("power"),
        "pct": row.get("pct"),
        "m_net": row.get("m_net"),
        "amount": row.get("amount"),
        "zt": row.get("zt"),
        "sort": row.get("sort"),
    }


def _merge_plate(base: dict[str, Any], plate: dict | None) -> dict[str, Any]:
    """点查结果覆盖空字段；不覆盖已有有效值（榜单涨幅优先于可疑点查）。"""
    if not plate:
        return base
    out = dict(base)
    for key in ("power", "pct", "m_net", "amount", "zt", "sort"):
        if out.get(key) is None and plate.get(key) is not None:
            out[key] = plate[key]
    return out


def _fetch_plate_map(codes: list[str], *, date: str | None) -> dict[str, dict]:
    """并行点查指定板块。"""
    uniq = []
    seen: set[str] = set()
    for c in codes:
        cs = str(c or "").strip()
        if not cs or cs in seen:
            continue
        seen.add(cs)
        uniq.append(cs)
    if not uniq:
        return {}
    out: dict[str, dict] = {}

    def _one(code: str):
        return code, mb.plate_info(code, date=date)

    workers = min(8, len(uniq))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, c) for c in uniq]
        for fut in as_completed(futs):
            try:
                code, info = fut.result()
            except Exception:  # noqa: BLE001
                continue
            if info:
                out[code] = info
    return out


def _build_tracked(
    *,
    y_blocks: list[dict],
    follows: list[dict],
    index: dialect.KplNameIndex,
) -> list[dict[str, Any]]:
    """合并人气热点与收藏，产出待跟踪列表（含映射状态）。"""
    by_code: dict[str, dict[str, Any]] = {}

    for row in y_blocks:
        power = row.get("power")
        if power is None or int(power) <= _HOT_POWER:
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        by_code[code] = {
            "code": code,
            "name": str(row.get("name") or code),
            "tags": [_TAG_HOT],
            "map_status": "matched",
            "follow": None,
            "y_rank": row,
        }

    unmatched_follows: list[dict[str, Any]] = []
    for fb in follows:
        hit = dialect.resolve_ths_block(fb, index)
        if hit.get("status") != "matched" or not hit.get("code"):
            unmatched_follows.append({
                "code": "",
                "name": str(fb.get("name") or fb.get("id") or ""),
                "tags": [_TAG_FOLLOW],
                "map_status": hit.get("status") or "unmatched",
                "follow": {
                    "kind": str(fb.get("kind") or ""),
                    "id": str(fb.get("id") or ""),
                    "name": str(fb.get("name") or ""),
                },
                "y_rank": None,
                "mapped": hit.get("mapped") or "",
            })
            continue
        code = str(hit["code"])
        entry = by_code.get(code)
        if entry:
            if _TAG_FOLLOW not in entry["tags"]:
                entry["tags"].append(_TAG_FOLLOW)
            entry["follow"] = {
                "kind": str(fb.get("kind") or ""),
                "id": str(fb.get("id") or ""),
                "name": str(fb.get("name") or ""),
            }
            if hit.get("name") and not entry.get("name"):
                entry["name"] = hit["name"]
        else:
            by_code[code] = {
                "code": code,
                "name": str(hit.get("name") or fb.get("name") or code),
                "tags": [_TAG_FOLLOW],
                "map_status": "matched",
                "follow": {
                    "kind": str(fb.get("kind") or ""),
                    "id": str(fb.get("id") or ""),
                    "name": str(fb.get("name") or ""),
                },
                "y_rank": index.get(code),
            }

    items = list(by_code.values()) + unmatched_follows

    def _sort_key(it: dict) -> tuple:
        tags = it.get("tags") or []
        hot = 0 if _TAG_HOT in tags else 1
        y = it.get("y_rank") or {}
        power = y.get("power")
        power_key = -(int(power) if power is not None else -1)
        return (hot, power_key, str(it.get("name") or ""))

    items.sort(key=_sort_key)
    return items


def snapshot() -> dict:
    """重点板块跟踪快照（今 vs 昨）。"""

    def build():
        as_of, prev, is_live = trade_calendar.resolve_as_of()
        if not as_of:
            return {
                "available": False,
                "reason": "无法锚定交易日场次",
                "as_of": None,
                "prev": None,
                "is_live": False,
                "blocks": [],
                "updated": china_now().strftime("%Y-%m-%d %H:%M"),
            }

        y_pack = mb.ranking_for_date(prev) if prev else {
            "available": False,
            "blocks": [],
            "from_archive": False,
            "reason": "无上一交易日",
        }
        y_blocks = list(y_pack.get("blocks") or []) if y_pack.get("available") else []

        # 今日榜仅作名称索引与涨幅补齐（点查为主）
        t_rows = mb.fetch_ranking_catalog(date=None)
        # 若今日实时榜空（周末），用 as_of 定稿榜作索引
        if not t_rows:
            t_pack = mb.ranking_for_date(as_of)
            t_rows = list(t_pack.get("blocks") or []) if t_pack.get("available") else []

        index = dialect.build_kpl_index(y_blocks)
        index.extend(t_rows)

        follows = mfb.load_blocks()
        tracked = _build_tracked(y_blocks=y_blocks, follows=follows, index=index)

        # 喂未映射名称进同花顺待匹配（与 mood_block 一致）
        try:
            from ths_block.processor import feed as ths_feed  # noqa: PLC0415

            pending_names = [
                str(it.get("name") or it.get("mapped") or "")
                for it in tracked
                if it.get("map_status") == "unmatched"
            ]
            pending_names = [n for n in pending_names if n]
            if pending_names:
                ths_feed("focus_block", pending_names)
        except Exception:  # noqa: BLE001
            pass

        codes = [str(it["code"]) for it in tracked if it.get("code")]
        # 昨日：榜内已有则复用；缺的再点查
        need_y = []
        y_rank_map = {str(r.get("code") or ""): r for r in y_blocks}
        for it in tracked:
            code = str(it.get("code") or "")
            if not code:
                continue
            if code not in y_rank_map:
                need_y.append(code)
        y_plate = _fetch_plate_map(need_y, date=prev) if prev and need_y else {}

        # 今日：一律点查（指定板块）；涨幅若空再从今日榜补
        t_rank_map = {str(r.get("code") or ""): r for r in t_rows}
        t_plate = _fetch_plate_map(codes, date=None if is_live else as_of)

        blocks_out: list[dict[str, Any]] = []
        for it in tracked:
            code = str(it.get("code") or "")
            y_base = _metrics_from_rank_row(y_rank_map.get(code) or it.get("y_rank"))
            y_m = _merge_plate(y_base, y_plate.get(code))
            if is_live:
                t_m = _merge_plate(_metrics_from_rank_row(None), t_plate.get(code))
                # 盘中点查涨幅不可靠时，用实时榜补 pct
                if t_m.get("pct") is None and code in t_rank_map:
                    t_m["pct"] = t_rank_map[code].get("pct")
                    if t_m.get("speed") is None:
                        t_m["speed"] = t_rank_map[code].get("speed")
            else:
                # 非盘中：as_of 定稿点查；榜内复用涨幅/人气
                t_base = _metrics_from_rank_row(t_rank_map.get(code))
                t_m = _merge_plate(t_base, t_plate.get(code))

            tags = list(it.get("tags") or [])
            blocks_out.append({
                "code": code or None,
                "name": it.get("name") or "",
                "tags": tags,
                "tag_labels": [_TAG_LABELS.get(t, t) for t in tags],
                "map_status": it.get("map_status") or "matched",
                "follow": it.get("follow"),
                "today": t_m,
                "yesterday": y_m,
            })

        available = bool(blocks_out) or bool(follows) or bool(y_blocks)
        reason = None
        if not blocks_out:
            if not y_pack.get("available") and not follows:
                reason = y_pack.get("reason") or "暂无重点板块（无人气热点且未收藏）"
            elif not blocks_out:
                reason = "暂无重点板块（昨日无人气>5000且收藏未映射到开盘啦）"

        return {
            "available": available and bool(blocks_out),
            "reason": reason if not blocks_out else None,
            "as_of": as_of,
            "prev": prev,
            "is_live": is_live,
            "hot_power": _HOT_POWER,
            "yesterday_from_archive": bool(y_pack.get("from_archive")),
            "blocks": blocks_out,
            "updated": china_now().strftime("%Y-%m-%d %H:%M"),
        }

    live = trade_calendar.is_calendar_session_live()
    ttl = _TTL if live else _OFFSESSION_TTL
    as_of, prev, _ = trade_calendar.resolve_as_of()
    key = f"focus_blocks:{as_of or 'na'}:{prev or 'na'}:{'L' if live else 'O'}"
    return _cached(key, ttl, build) or {
        "available": False,
        "reason": "重点板块取数失败",
        "blocks": [],
    }
