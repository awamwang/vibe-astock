"""消息输入解析：粘贴、结构化 JSON、财经日历。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from .schemas import ImpactTarget, IngestPayload, RawMessageDraft

BEIJING = timezone(timedelta(hours=8))
CALENDAR_SCHEMA_ID = "market-event-calendar/v4"

_CATEGORY_MARKS: dict[str, str] = {
    "必看大事": "must_watch",
    "关键数据": "key_data",
    "行业会展": "industry_exhibition",
}

_TARGET_KIND_MAP: dict[str, str] = {
    "sector": "sector",
    "stock": "stock",
    "subject": "theme",
}


def _now_str() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _draft_key() -> str:
    return f"draft_{uuid.uuid4().hex[:8]}"


def _split_plain(text: str, mode: str = "auto") -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if mode == "single":
        return [text]
    chunks: list[str] = []
    if mode in ("auto", "blank"):
        parts = re.split(r"\n\s*\n+", text)
        if len(parts) > 1:
            chunks = [p.strip() for p in parts if p.strip()]
    if not chunks and mode in ("auto", "rule"):
        parts = re.split(r"(?:^|\n)(?:-{3,}|={3,}|\*{3,})(?:\n|$)", text)
        if len(parts) > 1:
            chunks = [p.strip() for p in parts if p.strip()]
    if not chunks and mode in ("auto", "numbered"):
        parts = re.split(r"(?:^|\n)\d+[.、)\]]\s*", text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            chunks = parts
    if not chunks:
        chunks = [text]
    return chunks


def _first_str(d: dict[str, Any], keys: list[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _ms_to_beijing_str(ms: int | float) -> str:
    dt = datetime.fromtimestamp(float(ms) / 1000, tz=BEIJING)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _is_calendar_v4(doc: Any) -> bool:
    return isinstance(doc, dict) and isinstance(doc.get("events"), list)


_IMPACT_BY_IMPORTANCE = ("noise", "low", "medium", "high", "critical")


def importance_to_impact(level: Any) -> str:
    """财经日历 importanceLevel 1~5 → 系统 impact_level（从低到高）。"""
    try:
        n = int(level)
    except (TypeError, ValueError):
        return "medium"
    n = max(1, min(5, n))
    return _IMPACT_BY_IMPORTANCE[n - 1]


def _calendar_targets(raw_targets: Any) -> list[ImpactTarget]:
    out: list[ImpactTarget] = []
    if not isinstance(raw_targets, list):
        return out
    for t in raw_targets:
        if not isinstance(t, dict):
            continue
        kind = _TARGET_KIND_MAP.get(str(t.get("type") or ""), "other")
        code = str(t.get("code") or "").strip() or None
        out.append(ImpactTarget(kind=kind, code=code, name=str(t.get("name") or "")))
    return out


def _draft_from_calendar_v4_event(
    event: dict[str, Any],
    *,
    label: str,
    calendar_meta: dict[str, Any] | None = None,
) -> RawMessageDraft | None:
    title = str(event.get("title") or "").strip()
    if not title:
        return None
    start_ms = event.get("startTime")
    effective_at = _ms_to_beijing_str(start_ms) if start_ms is not None else None
    category = str(event.get("category") or "").strip()
    importance = event.get("importanceLevel")
    impact_level = importance_to_impact(importance)
    keywords = [category] if category else []
    marks: list[str] = []
    mark_key = _CATEGORY_MARKS.get(category)
    if mark_key:
        marks.append(mark_key)
    if isinstance(importance, int) and importance >= 4:
        marks.append("flame")
    meta: dict[str, Any] = {
        "format": "calendar",
        "calendar_schema": CALENDAR_SCHEMA_ID,
        "importance_level": importance,
        "impact_level": impact_level,
        "category": category,
    }
    if calendar_meta:
        meta["calendar_meta"] = calendar_meta
    return RawMessageDraft(
        draft_key=_draft_key(),
        source_id="calendar",
        source_label=label or "财经大事日历",
        content=title,
        title=title,
        keywords=keywords,
        marks=marks,
        external_ref=str(event.get("id") or "").strip() or None,
        produced_at=effective_at or _now_str(),
        effective_mode="scheduled",
        effective_at=effective_at,
        targets=_calendar_targets(event.get("targets")),
        meta=meta,
    )


def _parse_calendar_v4(doc: dict[str, Any], *, label: str) -> list[RawMessageDraft]:
    meta_block = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    source = meta_block.get("source") if isinstance(meta_block.get("source"), dict) else {}
    source_name = str(source.get("brand_display") or source.get("name") or "").strip()
    calendar_label = label or source_name or "财经大事日历"
    calendar_meta = {
        "title": meta_block.get("title"),
        "month": meta_block.get("month"),
        "year": meta_block.get("year"),
        "source": source,
        "disclaimer": meta_block.get("disclaimer"),
        "total_events": meta_block.get("total_events"),
        "legend": doc.get("legend"),
    }
    drafts: list[RawMessageDraft] = []
    for event in doc.get("events") or []:
        if not isinstance(event, dict):
            continue
        draft = _draft_from_calendar_v4_event(event, label=calendar_label, calendar_meta=calendar_meta)
        if draft:
            drafts.append(draft)
    return drafts


def _collect_calendar_docs(payload: IngestPayload) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if payload.text:
        try:
            parsed = json.loads(payload.text)
        except json.JSONDecodeError:
            parsed = None
        if _is_calendar_v4(parsed):
            docs.append(parsed)
        elif isinstance(parsed, list):
            for item in parsed:
                if _is_calendar_v4(item):
                    docs.append(item)
    for item in payload.items or []:
        if _is_calendar_v4(item):
            docs.append(item)
    return docs


def _parse_targets(item: dict[str, Any]) -> list[ImpactTarget]:
    out: list[ImpactTarget] = []
    for key in ("targets", "标的", "blocks", "stocks"):
        val = item.get(key)
        if not isinstance(val, list):
            continue
        for t in val:
            if isinstance(t, str):
                out.append(ImpactTarget(kind="other", name=t))
            elif isinstance(t, dict):
                kind = t.get("kind") or t.get("type") or "other"
                out.append(
                    ImpactTarget(
                        kind=kind,
                        code=t.get("code") or t.get("symbol") or t.get("Symbol"),
                        name=t.get("name") or t.get("Name") or "",
                    )
                )
    return out


def parse_ingest(payload: IngestPayload, *, source_label: str = "") -> list[RawMessageDraft]:
    fmt = payload.format
    opts = payload.options or {}
    split_mode = str(opts.get("split_mode", "auto"))
    sid = payload.source_id or "paste"
    label = source_label or _default_label(sid)

    if fmt == "plain":
        text = (payload.text or "").strip()
        parts = _split_plain(text, split_mode)
        drafts: list[RawMessageDraft] = []
        for i, part in enumerate(parts):
            title = part.split("\n", 1)[0][:120] if part else ""
            drafts.append(
                RawMessageDraft(
                    draft_key=_draft_key(),
                    source_id=sid,
                    source_label=label,
                    content=part,
                    title=title,
                    meta={"split_index": i, "split_mode": split_mode},
                )
            )
        return drafts

    if fmt == "structured":
        items = payload.items or []
        if not items and payload.text:
            import json

            try:
                parsed = json.loads(payload.text)
                items = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                items = []
        drafts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _first_str(item, ["title", "标题", "Title", "新闻标题"])
            content = _first_str(item, ["content", "正文", "Content", "summary", "摘要", "新闻内容", "内容"])
            if not content and title:
                content = title
            kw_raw = item.get("keywords") or item.get("关键词")
            keywords = kw_raw if isinstance(kw_raw, list) else ([str(kw_raw)] if kw_raw else [])
            url = _first_str(item, ["url", "链接", "link", "新闻链接"])
            marks_raw = item.get("marks") or item.get("标记")
            marks = marks_raw if isinstance(marks_raw, list) else ([str(marks_raw)] if marks_raw else [])
            produced = _first_str(item, ["produced_at", "time", "发布时间", "发布日期"])
            ext = _first_str(item, ["id", "external_ref", "Id"])
            drafts.append(
                RawMessageDraft(
                    draft_key=_draft_key(),
                    source_id=sid,
                    source_label=label,
                    content=content or title,
                    title=title,
                    keywords=keywords,
                    url=url,
                    marks=marks,
                    external_ref=ext or None,
                    produced_at=produced or None,
                    targets=_parse_targets(item),
                    meta={"format": "structured"},
                )
            )
        return drafts

    if fmt == "calendar":
        v4_docs = _collect_calendar_docs(payload)
        if v4_docs:
            drafts: list[RawMessageDraft] = []
            for doc in v4_docs:
                drafts.extend(_parse_calendar_v4(doc, label=label))
            return drafts

        items: list[dict[str, Any]] = []
        if payload.items:
            items = [i for i in payload.items if isinstance(i, dict)]
        elif payload.text:
            try:
                parsed = json.loads(payload.text)
                if isinstance(parsed, list):
                    items = [i for i in parsed if isinstance(i, dict)]
                elif isinstance(parsed, dict):
                    items = [parsed]
            except json.JSONDecodeError:
                items = []
        legacy_drafts: list[RawMessageDraft] = []
        for item in items:
            title = _first_str(item, ["title", "标题", "事件"])
            content = _first_str(item, ["content", "详情", "说明"]) or title
            effective_at = _first_str(item, ["effective_at", "生效时间", "datetime", "时间"])
            keywords_raw = item.get("keywords") or item.get("关键词") or item.get("tags")
            keywords = keywords_raw if isinstance(keywords_raw, list) else (
                [str(keywords_raw)] if keywords_raw else []
            )
            legacy_drafts.append(
                RawMessageDraft(
                    draft_key=_draft_key(),
                    source_id="calendar",
                    source_label=label or "财经大事日历",
                    content=content,
                    title=title,
                    keywords=keywords,
                    url=_first_str(item, ["url", "链接"]),
                    marks=item.get("marks") if isinstance(item.get("marks"), list) else [],
                    produced_at=_first_str(item, ["produced_at", "公布时间"]) or _now_str(),
                    effective_mode="scheduled",
                    effective_at=effective_at or None,
                    targets=_parse_targets(item),
                    meta={"format": "calendar"},
                )
            )
        return legacy_drafts

    return []


def merge_drafts(drafts: list[RawMessageDraft], indices: list[int]) -> RawMessageDraft:
    """合并选中的草稿为一条。"""
    selected = [drafts[i] for i in sorted(indices) if 0 <= i < len(drafts)]
    if not selected:
        raise ValueError("无有效草稿可合并")
    content = "\n\n".join(d.content for d in selected)
    title = selected[0].title or content.split("\n", 1)[0][:120]
    keywords: list[str] = []
    marks: list[str] = []
    targets: list[ImpactTarget] = []
    for d in selected:
        keywords.extend(d.keywords)
        marks.extend(d.marks)
        targets.extend(d.targets)
    return RawMessageDraft(
        draft_key=_draft_key(),
        source_id=selected[0].source_id,
        source_label=selected[0].source_label,
        content=content,
        title=title,
        keywords=list(dict.fromkeys(keywords)),
        marks=list(dict.fromkeys(marks)),
        targets=targets,
        meta={"merged_from": [d.draft_key for d in selected]},
    )


def resplit_draft(draft: RawMessageDraft, mode: str = "blank") -> list[RawMessageDraft]:
    parts = _split_plain(draft.content, mode)
    return [
        RawMessageDraft(
            draft_key=_draft_key(),
            source_id=draft.source_id,
            source_label=draft.source_label,
            content=p,
            title=p.split("\n", 1)[0][:120],
            keywords=list(draft.keywords),
            url=draft.url,
            marks=list(draft.marks),
            meta={"resplit_from": draft.draft_key, "split_mode": mode},
        )
        for p in parts
    ]


def _default_label(source_id: str) -> str:
    return {
        "paste": "粘贴录入",
        "structured": "结构化 JSON",
        "calendar": "财经大事日历",
        "xgb_msgs": "选股宝快讯",
        "cls_telegraph": "财联社电报",
    }.get(source_id, source_id)
