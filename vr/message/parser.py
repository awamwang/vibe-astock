"""消息输入解析：粘贴、结构化 JSON、财经日历。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from .schemas import ImpactTarget, IngestPayload, RawMessageDraft

BEIJING = timezone(timedelta(hours=8))


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
            title = _first_str(item, ["title", "标题", "事件"])
            content = _first_str(item, ["content", "详情", "说明"]) or title
            effective_at = _first_str(item, ["effective_at", "生效时间", "datetime", "时间"])
            keywords_raw = item.get("keywords") or item.get("关键词") or item.get("tags")
            keywords = keywords_raw if isinstance(keywords_raw, list) else (
                [str(keywords_raw)] if keywords_raw else []
            )
            drafts.append(
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
        return drafts

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
