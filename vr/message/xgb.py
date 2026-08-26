"""选股宝 pc/msgs 抓取与字段映射。"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

from .schemas import ImpactTarget, RawMessageDraft
from . import store

XGB_BASE = "https://api.xuangubao.cn"
DEFAULT_SUBJIDS = "9,10,723,35,469,821"
BEIJING = timezone(timedelta(hours=8))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://xuangubao.cn",
        "Referer": "https://xuangubao.cn/",
    }


def symbol_to_code(symbol: str) -> str | None:
    """301666.SZ → 301666"""
    if not symbol:
        return None
    m = re.match(r"^(\d{6})", symbol.strip())
    return m.group(1) if m else None


def _ts_to_str(ts: int | float | None) -> str:
    if ts is None:
        return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    try:
        return datetime.fromtimestamp(int(ts), BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def map_xgb_item(item: dict[str, Any]) -> RawMessageDraft:
    msg_id = str(item.get("Id") or "")
    title = (item.get("Title") or "").strip()
    summary = (item.get("Summary") or "").strip()
    content = (item.get("Content") or "").strip()
    body = content or summary or title
    ts = item.get("CreatedAtInSec")
    if ts is None and item.get("CreatedAt"):
        try:
            dt = datetime.fromisoformat(str(item["CreatedAt"]).replace("Z", "+00:00"))
            ts = int(dt.timestamp())
        except ValueError:
            ts = None
    targets: list[ImpactTarget] = []
    for s in item.get("AllStocks") or item.get("Stocks") or []:
        if not isinstance(s, dict):
            continue
        code = symbol_to_code(str(s.get("Symbol") or ""))
        name = str(s.get("Name") or code or "")
        if name or code:
            targets.append(ImpactTarget(kind="stock", code=code, name=name))
    for b in item.get("BkjInfoArr") or []:
        if not isinstance(b, dict):
            continue
        targets.append(
            ImpactTarget(
                kind="theme",
                code=str(b.get("Id") or "") or None,
                name=str(b.get("Name") or ""),
            )
        )
    marks: list[str] = []
    if item.get("IsWithdrawn"):
        marks.append("withdrawn")
    fmt = item.get("FlashMessageType")
    if fmt:
        marks.append(str(fmt))
    impact = item.get("Impact")
    if impact is not None:
        marks.append(f"impact:{impact}")
    subj = item.get("SubjIds")
    keywords = [str(x) for x in subj] if isinstance(subj, list) else []
    url = str(item.get("Image") or "")
    return RawMessageDraft(
        draft_key=f"xgb_{msg_id}",
        source_id="xgb_msgs",
        source_label="选股宝快讯",
        content=body,
        title=title,
        keywords=keywords,
        url=url if url.startswith("http") else "",
        marks=marks,
        external_ref=msg_id or None,
        produced_at=_ts_to_str(ts),
        targets=targets,
        meta={"xgb_raw": item, "_targets_json": [t.model_dump() for t in targets]},
    )


def fetch_pc_msgs(
    *,
    subjids: str | None = None,
    limit: int = 30,
    path: str | None = None,
) -> dict[str, Any]:
    """拉取选股宝 pc/msgs，写入 raw_message，返回统计。"""
    subj = subjids or os.environ.get("XGB_SUBJIDS", DEFAULT_SUBJIDS)
    url = f"{XGB_BASE}/api/pc/msgs?subjids={subj}&limit={limit}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    head = data.get("HeadMark")
    tail = data.get("TailMark")
    new_msgs = data.get("NewMsgs") or []
    updated = data.get("UpdatedMsgs") or []
    deleted = data.get("DeletedMsgs") or []

    drafts: list[RawMessageDraft] = []
    for item in new_msgs + updated:
        if isinstance(item, dict):
            drafts.append(map_xgb_item(item))

    inserted = store.insert_raw_batch(drafts, path=path)

    withdrawn = 0
    for item in deleted:
        if isinstance(item, dict) and item.get("Id"):
            if store.mark_withdrawn("xgb_msgs", str(item["Id"]), path=path):
                withdrawn += 1
        elif isinstance(item, str):
            if store.mark_withdrawn("xgb_msgs", item, path=path):
                withdrawn += 1

    for raw in inserted:
        store.upsert_analyzed_from_raw(raw, path=path)

    store.set_poll_state(
        "xgb_msgs",
        head_mark=str(head) if head is not None else None,
        tail_mark=str(tail) if tail is not None else None,
        last_error=None,
        path=path,
    )
    return {
        "fetched": len(new_msgs) + len(updated),
        "inserted": len(inserted),
        "withdrawn": withdrawn,
        "head_mark": head,
        "tail_mark": tail,
    }
