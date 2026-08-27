"""财联社电报 cls.cn 抓取与字段映射。"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

from .schemas import ImpactTarget, RawMessage, RawMessageDraft
from . import archive, store

# RSSHub lib/routes/cls/utils.ts
_CLS_SV = "8.7.9"
_CLS_APP = "CailianpressWeb"
_CLS_ROLL_URL = "https://www.cls.cn/v1/roll/get_roll_list"
BEIJING = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Referer": "https://www.cls.cn/telegraph",
        "Accept": "application/json, text/plain, */*",
    }


def _生成_sign(参数字典: dict[str, str]) -> str:
    """sign = MD5(SHA1(按 key 排序后的 query string))。"""
    有序 = sorted((k, v) for k, v in 参数字典.items() if v is not None)
    待签 = urllib.parse.urlencode(有序)
    sha1 = hashlib.sha1(待签.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def _构建_roll_查询(**extra: str) -> dict[str, str]:
    base: dict[str, str] = {
        "app": _CLS_APP,
        "category": "",
        "os": "web",
        "refresh_type": "1",
        "sv": _CLS_SV,
    }
    base.update({k: str(v) for k, v in extra.items() if v is not None})
    base["sign"] = _生成_sign({k: v for k, v in base.items() if k != "sign"})
    return base


def _ts_to_str(ts: int | float | None) -> str:
    if ts is None:
        return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    try:
        return datetime.fromtimestamp(int(ts), BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def level_to_impact(level: str | None) -> str:
    """财联社 level → 系统 impact_level 初值。"""
    return {"A": "high", "B": "medium", "C": "low"}.get(str(level or "").upper(), "medium")


def extract_subjects(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for s in item.get("subjects") or []:
        if isinstance(s, dict):
            name = str(s.get("subject_name") or s.get("name") or "").strip()
            if name:
                names.append(name)
        elif isinstance(s, str) and s.strip():
            names.append(s.strip())
    return names


def extract_targets(item: dict[str, Any]) -> list[ImpactTarget]:
    return [ImpactTarget(kind="theme", name=n) for n in extract_subjects(item)]


def map_cls_item(item: dict[str, Any]) -> RawMessageDraft:
    msg_id = str(item.get("id") or "")
    title = (item.get("title") or "").strip()
    content = (item.get("content") or "").strip()
    body = content or title
    if not title and body:
        title = body.split("\n", 1)[0][:120]
    subjects = extract_subjects(item)
    marks: list[str] = []
    level = str(item.get("level") or "").upper()
    if level == "A":
        marks.append("highlight")
    elif level:
        marks.append(f"level:{level.lower()}")
    url = str(item.get("shareurl") or "")
    return RawMessageDraft(
        draft_key=f"cls_{msg_id}",
        source_id="cls_telegraph",
        source_label="财联社电报",
        content=body,
        title=title,
        keywords=subjects,
        url=url if url.startswith("http") else "",
        marks=marks,
        external_ref=msg_id or None,
        produced_at=_ts_to_str(item.get("ctime")),
        targets=extract_targets(item),
        meta={
            "cls_raw": item,
            "cls_level": level or None,
            "_targets_json": [t.model_dump() for t in extract_targets(item)],
        },
    )


def _fetch_roll_page(*, last_time: int, rn: int, timeout: float = 20) -> list[dict[str, Any]]:
    query = _构建_roll_查询(last_time=str(last_time), rn=str(rn))
    url = f"{_CLS_ROLL_URL}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    roll = (body.get("data") or {}).get("roll_data") or []
    return [i for i in roll if isinstance(i, dict)]


def _item_id(item: dict[str, Any]) -> int:
    try:
        return int(item.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_roll_since_id(
    last_id: int,
    *,
    page_size: int | None = None,
    max_pages: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """翻页拉取 id 大于 last_id 的全部财联社电报，返回 (条目列表, 实际页数)。"""
    rn = page_size or int(os.environ.get("CLS_PAGE_RN", "50"))
    cap = max_pages or int(os.environ.get("CLS_MAX_PAGES", "30"))
    rn = max(1, min(rn, 100))
    cap = max(1, min(cap, 200))

    collected: list[dict[str, Any]] = []
    seen: set[int] = set()
    last_time = int(time.time())
    pages_used = 0

    for _ in range(cap):
        page = _fetch_roll_page(last_time=last_time, rn=rn)
        pages_used += 1
        if not page:
            break

        min_id = 0
        for item in page:
            mid = _item_id(item)
            if mid <= 0 or mid in seen:
                continue
            seen.add(mid)
            if mid > last_id:
                collected.append(item)
            if min_id == 0 or (0 < mid < min_id):
                min_id = mid

        if min_id > 0 and min_id <= last_id:
            break
        if len(page) < rn:
            break

        try:
            tail_ctime = int(page[-1].get("ctime") or 0)
        except (TypeError, ValueError):
            break
        if tail_ctime <= 0:
            break
        last_time = tail_ctime - 1

    collected.sort(key=_item_id)
    return collected, pages_used


def _analyzed_patch(raw: RawMessage, item: dict[str, Any]) -> dict[str, Any]:
    title = raw.title or (item.get("title") or "")
    summary = title[:120] if title else raw.content[:120]
    targets = raw.meta.get("_targets_json") or [t.model_dump() for t in extract_targets(item)]
    level = str(item.get("level") or raw.meta.get("cls_level") or "")
    return {
        "title": title,
        "summary": summary,
        "detail": raw.content,
        "keywords": list(raw.keywords),
        "url": raw.url,
        "marks": list(raw.marks),
        "targets": targets,
        "impact_level": level_to_impact(level),
    }


def fetch_telegraph(*, limit: int | None = None, path: str | None = None) -> dict[str, Any]:
    """翻页拉取 tail_mark 之后的财联社电报，增量入库并更新 tail_mark。"""
    state = store.get_poll_state("cls_telegraph", path=path)
    try:
        last_id = int(state.get("tail_mark") or 0)
    except (TypeError, ValueError):
        last_id = 0

    items, pages_used = fetch_roll_since_id(last_id)
    if limit is not None and limit > 0:
        items = items[:limit]
    elif lim := int(os.environ.get("CLS_FETCH_LIMIT", "0")):
        if lim > 0:
            items = items[:lim]

    drafts = [map_cls_item(i) for i in items]
    inserted = store.insert_raw_batch(drafts, path=path)

    synced = 0
    inserted_new = 0
    for raw in inserted:
        ext_id = _item_id({"id": raw.external_ref})
        is_new = last_id == 0 or ext_id > last_id
        if is_new:
            inserted_new += 1
        if last_id > 0 and 0 < ext_id <= last_id:
            continue
        cls_raw = raw.meta.get("cls_raw") if isinstance(raw.meta.get("cls_raw"), dict) else {}
        store.upsert_analyzed_from_raw(raw, patch=_analyzed_patch(raw, cls_raw), path=path)
        synced += 1

    max_id = last_id
    for i in items:
        mid = _item_id(i)
        if mid > max_id:
            max_id = mid

    new_ids = [_item_id({"id": d.external_ref}) for d in drafts if d.external_ref and _item_id({"id": d.external_ref}) > last_id]

    store.set_poll_state(
        "cls_telegraph",
        tail_mark=str(max_id) if max_id else None,
        last_error=None,
        path=path,
    )

    archive_stats = archive.archive_immediate_expired(main_path=path)

    return {
        "fetched": len(items),
        "pages_used": pages_used,
        "new_candidates": len(new_ids),
        "inserted": inserted_new,
        "updated": max(0, len(inserted) - inserted_new),
        "synced": synced,
        "tail_mark": str(max_id),
        "last_id": last_id,
        "archive": archive_stats,
    }
