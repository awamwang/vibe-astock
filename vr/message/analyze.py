"""消息 AI 结构化分析 —— 复用 vr/chat 的 LLM 调用（API / CLI）。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import store
from .schemas import AnalyzedMessage, ImpactTarget, RawMessage

_IMPACT = frozenset({"critical", "high", "medium", "low", "noise"})
_FRESHNESS = frozenset({"new", "follow_up", "duplicate", "rumor"})
_EFFECT = frozenset({
    "not_erupted", "pending_verify", "ongoing_hype", "already_hyped", "invalid",
})
_TARGET_KIND = frozenset({"market", "sector", "theme", "stock", "other"})
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")

JSON_SKELETON = """{
  "title": "标题，字符串",
  "summary": "一句话摘要，不超过120字",
  "keywords": ["关键词1", "关键词2"],
  "targets": [{"kind": "stock|sector|theme|market|other", "code": "6位代码或null", "name": "显示名"}],
  "impact_level": "critical|high|medium|low|noise",
  "freshness": "new|follow_up|duplicate|rumor",
  "effect_status": "not_erupted|pending_verify|ongoing_hype|already_hyped|invalid"
}"""

SYSTEM = """你是 A 股资讯整理助手。根据用户给出的单条消息原文，输出结构化 JSON。

硬性规则：
- 只做信息整理与客观标注；不推荐买卖、不预测涨跌、不给目标价。
- freshness（消息新旧）仅根据本条正文判断，禁止引用或假设系统里还有其他消息。
- duplicate=与常见公开信息高度重复；follow_up=同主题续报；rumor=未经证实的传闻；new=全新信息。
- effect_status 默认 not_erupted，除非正文明确提到已在炒作/已兑现等。

请严格只输出一个 JSON 对象，不要 markdown 代码块，不要解释。"""


def extract_first_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        start = text.find("{", idx)
        if start == -1:
            return None
        try:
            obj, _ = decoder.raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
            idx = start + 1
        except json.JSONDecodeError:
            idx = start + 1


def _llm_complete(cfg: dict, user: str, *, retry_hint: str = "") -> str:
    import chat as chat_layer
    import cli_runtime

    is_cli = str(cfg.get("provider", "")).startswith("cli-")
    instr = f"\n\nJSON 骨架（键名必须一致）：\n{JSON_SKELETON}"
    if retry_hint:
        instr += f"\n\n（上次输出不合规：{retry_hint}；请重新只输出合法 JSON。）"
    if is_cli:
        kind = str(cfg.get("provider", ""))[4:]
        return cli_runtime.run_cli(kind, SYSTEM, user + instr)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user + instr},
    ]
    data = chat_layer._call_llm(cfg, messages, use_tools=False)
    return data["choices"][0]["message"].get("content") or ""


def _norm_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if val is not None and str(val).strip():
        return [str(val).strip()]
    return []


def _extract_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;)")


def _merge_keywords(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for item in group:
            k = str(item).strip()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
    return out


def _target_key(t: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(t.get("kind") or "other"),
        str(t.get("code") or "").strip(),
        str(t.get("name") or "").strip(),
    )


def _merge_targets(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for t in group:
            key = _target_key(t)
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
    return out


def _existing_targets(raw: RawMessage, analyzed: AnalyzedMessage) -> list[dict[str, Any]]:
    if analyzed.targets:
        return [t.model_dump() for t in analyzed.targets]
    return [
        ImpactTarget.model_validate(t).model_dump()
        for t in (raw.meta.get("_targets_json") or [])
        if isinstance(t, dict)
    ]


def _norm_targets(val: Any) -> list[dict[str, Any]]:
    if not isinstance(val, list):
        return []
    out: list[dict[str, Any]] = []
    for t in val:
        if not isinstance(t, dict):
            continue
        kind = str(t.get("kind") or "other").strip()
        if kind not in _TARGET_KIND:
            kind = "other"
        code = t.get("code")
        code_s = str(code).strip() if code is not None else None
        if code_s == "":
            code_s = None
        name = str(t.get("name") or code_s or "").strip()
        if name or code_s:
            out.append({"kind": kind, "code": code_s, "name": name})
    return out


def _parse_llm_patch(obj: dict[str, Any], *, raw: RawMessage, analyzed: AnalyzedMessage) -> dict[str, Any]:
    """将 AI 结构化字段融合进已有数据；detail/marks/生效时间等不由 AI 改写。"""
    summary = str(obj.get("summary") or analyzed.summary or raw.title or raw.content[:120]).strip()
    if len(summary) > 120:
        summary = summary[:117] + "…"
    impact = str(obj.get("impact_level") or analyzed.impact_level or "medium")
    if impact not in _IMPACT:
        impact = analyzed.impact_level if analyzed.impact_level in _IMPACT else "medium"
    freshness = str(obj.get("freshness") or analyzed.freshness or "new")
    if freshness not in _FRESHNESS:
        freshness = analyzed.freshness if analyzed.freshness in _FRESHNESS else "new"
    effect = str(obj.get("effect_status") or analyzed.effect_status or "not_erupted")
    if effect not in _EFFECT:
        effect = analyzed.effect_status if analyzed.effect_status in _EFFECT else "not_erupted"
    existing_targets = _existing_targets(raw, analyzed)
    ai_targets = _norm_targets(obj.get("targets"))
    targets = _merge_targets(existing_targets, ai_targets)
    ai_title = str(obj.get("title") or "").strip()
    title = ai_title or analyzed.title or raw.title or summary[:80]
    detail = (raw.content or analyzed.detail or "").strip()
    keywords = _merge_keywords(
        list(raw.keywords),
        list(analyzed.keywords),
        _norm_list(obj.get("keywords")),
    )
    url = raw.url or analyzed.url or _extract_url(detail) or ""
    return {
        "title": title,
        "summary": summary,
        "detail": detail,
        "keywords": keywords,
        "url": url,
        "targets": targets,
        "impact_level": impact,
        "freshness": freshness,
        "effect_status": effect,
        "status": "draft",
        "analyzed_by": "ai",
    }


def build_user_prompt(raw: RawMessage, analyzed: AnalyzedMessage) -> str:
    parts = [
        "【来源】" + (raw.source_label or raw.source_id),
        "【产生时间】" + raw.produced_at,
    ]
    if raw.title or analyzed.title:
        parts.append("【标题】" + (raw.title or analyzed.title))
    if raw.keywords:
        parts.append("【已有标签】" + "、".join(raw.keywords))
    existing = _existing_targets(raw, analyzed)
    if existing:
        lines = []
        for t in existing:
            code_part = f"({t['code']})" if t.get("code") else ""
            lines.append(f"- {t['kind']}:{t['name']}{code_part}")
        parts.append("【已有标的】\n" + "\n".join(lines))
        parts.append("（分析时请保留以上已有标的，可补充但勿清空）")
    parts.append("【正文】\n" + (raw.content or analyzed.detail))
    return "\n".join(parts)


def analyze_one(cfg: dict, *, raw_id: str | None = None, analyzed_id: str | None = None) -> AnalyzedMessage:
    raw: RawMessage | None = None
    analyzed: AnalyzedMessage | None = None

    if analyzed_id:
        analyzed = store.get_analyzed(analyzed_id)
        if not analyzed:
            raise ValueError(f"未找到分析消息 {analyzed_id}")
        if analyzed.raw_ids:
            raw = store.get_raw(analyzed.raw_ids[0])
        if not raw:
            raise ValueError("缺少关联原始消息")
    elif raw_id:
        raw = store.get_raw(raw_id)
        if not raw:
            raise ValueError(f"未找到原始消息 {raw_id}")
        analyzed = store.get_analyzed_for_raw(raw_id)
        if not analyzed:
            analyzed = store.upsert_analyzed_from_raw(raw)
    else:
        raise ValueError("需要 raw_id 或 analyzed_id")

    assert raw is not None and analyzed is not None
    user = build_user_prompt(raw, analyzed)
    last_err = ""
    obj: dict[str, Any] | None = None
    for attempt in range(2):
        text = _llm_complete(cfg, user, retry_hint=last_err if attempt else "")
        obj = extract_first_json(text)
        if obj:
            break
        last_err = "未找到 JSON 对象"
    if not obj:
        raise RuntimeError("模型未返回可解析的 JSON")

    patch = _parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    # 已手动指定优先级时，AI 不再改写工作档（初始档本就不在 AI patch 中）
    if analyzed.impact_manual:
        patch.pop("impact_level", None)
    updated = store.update_analyzed(analyzed.id, patch)
    if not updated:
        raise RuntimeError("写入分析结果失败")
    return updated


def run_batch_stream(cfg: dict, *, raw_ids: list[str], analyzed_ids: list[str]):
    """逐条分析，yield NDJSON 事件。"""
    tasks: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rid in raw_ids:
        if rid and rid not in seen:
            tasks.append(("raw", rid))
            seen.add(rid)
    for aid in analyzed_ids:
        if aid and aid not in seen:
            tasks.append(("analyzed", aid))
            seen.add(aid)

    total = len(tasks)
    if not total:
        yield {"type": "error", "message": "未选择任何消息"}
        return

    ok = 0
    for i, (kind, tid) in enumerate(tasks, 1):
        yield {"type": "progress", "current": i, "total": total, "id": tid, "kind": kind}
        try:
            if kind == "raw":
                result = analyze_one(cfg, raw_id=tid)
            else:
                result = analyze_one(cfg, analyzed_id=tid)
            ok += 1
            yield {"type": "item", "data": result.model_dump()}
        except Exception as e:  # noqa: BLE001
            yield {"type": "item_error", "id": tid, "message": str(e)[:500]}
    yield {"type": "done", "total": total, "ok": ok, "failed": total - ok}
