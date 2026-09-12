"""消息 AI 结构化分析 —— 复用 vr/chat 的 LLM 调用（API / CLI）。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import store
from .follow import initial_impact_with_follow
from .schemas import AnalyzedMessage, ImpactLevel, ImpactTarget, RawMessage

_IMPACT = frozenset({"critical", "high", "medium", "low", "noise"})
_IMPACT_ORDER = ("noise", "low", "medium", "high", "critical")
_FRESHNESS = frozenset({"new", "follow_up", "duplicate", "rumor"})
_EFFECT = frozenset({
    "not_erupted", "pending_verify", "ongoing_hype", "already_hyped", "invalid",
})
_TARGET_KIND = frozenset({"market", "sector", "theme", "stock", "other"})
_SCOPE = frozenset({"market", "sector", "theme", "stock", "other"})
_SCOPE_WEIGHT = {
    "market": 5.0,
    "sector": 4.0,
    "theme": 3.5,
    "stock": 2.5,
    "other": 1.5,
}
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")

JSON_SKELETON = """{
  "title": "标题，字符串",
  "summary": "一句话摘要，不超过120字",
  "keywords": ["关键词1", "关键词2"],
  "targets": [{"kind": "stock|sector|theme|market|other", "code": "6位代码或null", "name": "显示名"}],
  "scope": "market|sector|theme|stock|other",
  "magnitude": "1-5整数，信息力度",
  "actionability": "1-5整数，可落到标的/题材的程度",
  "credibility": "1-5整数，官宣高、传闻低",
  "time_sensitivity": "1-5整数，盘中突发高、隔夜已知低",
  "is_rumor": false,
  "rationale": "一句判定理由，先写理由再填因子",
  "freshness": "new|follow_up|duplicate|rumor",
  "effect_status": "not_erupted|pending_verify|ongoing_hype|already_hyped|invalid"
}"""

SYSTEM = """你是 A 股资讯整理助手。根据用户给出的单条消息原文，输出结构化 JSON。

硬性规则：
- 只做信息整理与客观标注；不推荐买卖、不预测涨跌、不给目标价。
- 不要直接输出优先级档位；只输出因子字段与 rationale。服务端会按因子合成客观档。
- 禁止用「可能影响股价」抬高 magnitude / actionability；只按信息增量与影响面。
- freshness（消息新旧）仅根据本条正文判断，禁止引用或假设系统里还有其他消息。
- duplicate=与常见公开信息高度重复；follow_up=同主题续报；rumor=未经证实的传闻；new=全新信息。
- effect_status 默认 not_erupted，除非正文明确提到已在炒作/已兑现等。
- 必须先写 rationale（一句），再填各 1–5 因子与 scope。

五档锚点（供你校准因子力度，勿输出档位名）：
- critical 级力度：央行/证监会重大政策、系统性风险、指数级事件。
- high 级力度：核心板块监管、重大并购、龙头业绩变脸等。
- medium 级力度：一般公司公告、常规宏观数据。
- low 级力度：软性解读、行业动态。
- noise 级力度：广告、重复转发、无增量信息；「吓人标题但无实质」应落在噪声侧。

请严格只输出一个 JSON 对象，不要 markdown 代码块，不要解释。"""

IMPACT_JSON_SKELETON = """{
  "scope": "market|sector|theme|stock|other",
  "magnitude": "1-5整数，信息力度",
  "actionability": "1-5整数，可落到标的/题材的程度",
  "credibility": "1-5整数，官宣高、传闻低",
  "time_sensitivity": "1-5整数，盘中突发高、隔夜已知低",
  "is_rumor": false,
  "rationale": "一句判定理由，先写理由再填因子"
}"""

IMPACT_SYSTEM = """你是 A 股资讯整理助手。根据用户给出的单条消息，只判定影响力度相关因子。

硬性规则：
- 只做客观因子标注；不推荐买卖、不预测涨跌、不给目标价。
- 不要输出优先级档位名；只输出因子与 rationale。服务端会合成客观档。
- 禁止用「可能影响股价」抬高 magnitude / actionability；只按信息增量与影响面。
- 必须先写 rationale（一句），再填各 1–5 因子与 scope。
- 不要改写标题、摘要、标的或其它字段。

五档锚点（供你校准因子力度，勿输出档位名）：
- critical 级力度：央行/证监会重大政策、系统性风险、指数级事件。
- high 级力度：核心板块监管、重大并购、龙头业绩变脸等。
- medium 级力度：一般公司公告、常规宏观数据。
- low 级力度：软性解读、行业动态。
- noise 级力度：广告、重复转发、无增量信息；「吓人标题但无实质」应落在噪声侧。

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


def _llm_complete(
    cfg: dict,
    user: str,
    *,
    retry_hint: str = "",
    system: str = SYSTEM,
    skeleton: str = JSON_SKELETON,
) -> str:
    import chat as chat_layer
    import cli_runtime

    is_cli = str(cfg.get("provider", "")).startswith("cli-")
    instr = f"\n\nJSON 骨架（键名必须一致）：\n{skeleton}"
    if retry_hint:
        instr += f"\n\n（上次输出不合规：{retry_hint}；请重新只输出合法 JSON。）"
    if is_cli:
        kind = str(cfg.get("provider", ""))[4:]
        return cli_runtime.run_cli(kind, system, user + instr)
    messages = [
        {"role": "system", "content": system},
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


def _merge_targets(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .content_targets import merge_targets

    return [t.model_dump() for t in merge_targets(None, *groups)]


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


def _clamp_score_1_5(val: Any, default: float = 3.0) -> float:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return default
    return max(1.0, min(5.0, n))


def _demote_level(level: str) -> str:
    try:
        idx = _IMPACT_ORDER.index(level)
    except ValueError:
        return "medium"
    return _IMPACT_ORDER[max(0, idx - 1)]


def _cap_level(level: str, cap: str) -> str:
    try:
        li = _IMPACT_ORDER.index(level)
        ci = _IMPACT_ORDER.index(cap)
    except ValueError:
        return level
    return _IMPACT_ORDER[min(li, ci)]


def _score_to_level(score: float) -> ImpactLevel:
    if score >= 4.5:
        return "critical"
    if score >= 3.7:
        return "high"
    if score >= 2.8:
        return "medium"
    if score >= 1.8:
        return "low"
    return "noise"


def synthesize_ai_impact_level(
    factors: dict[str, Any],
    *,
    freshness: str = "new",
) -> ImpactLevel:
    """按固定权重将 AI 因子合成客观档（不含关注升档）。"""
    scope = str(factors.get("scope") or "other").strip()
    if scope not in _SCOPE:
        scope = "other"
    magnitude = _clamp_score_1_5(factors.get("magnitude"), 3.0)
    actionability = _clamp_score_1_5(factors.get("actionability"), 3.0)
    credibility = _clamp_score_1_5(factors.get("credibility"), 3.0)
    time_sensitivity = _clamp_score_1_5(factors.get("time_sensitivity"), 3.0)
    scope_w = _SCOPE_WEIGHT.get(scope, 1.5)
    score = (
        0.30 * magnitude
        + 0.25 * actionability
        + 0.20 * time_sensitivity
        + 0.15 * credibility
        + 0.10 * scope_w
    )
    level: str = _score_to_level(score)
    is_rumor = bool(factors.get("is_rumor")) or freshness == "rumor"
    if is_rumor:
        level = _demote_level(level)
    if freshness == "duplicate":
        level = _cap_level(level, "medium")
    return level  # type: ignore[return-value]


def _parse_impact_factors(obj: dict[str, Any]) -> dict[str, Any] | None:
    """从模型输出抽取因子；缺关键分数字段则视为无因子（走旧字段回退）。"""
    keys = ("magnitude", "actionability", "credibility", "time_sensitivity")
    if not any(k in obj for k in keys):
        return None
    scope = str(obj.get("scope") or "other").strip()
    if scope not in _SCOPE:
        scope = "other"
    return {
        "scope": scope,
        "magnitude": int(round(_clamp_score_1_5(obj.get("magnitude"), 3.0))),
        "actionability": int(round(_clamp_score_1_5(obj.get("actionability"), 3.0))),
        "credibility": int(round(_clamp_score_1_5(obj.get("credibility"), 3.0))),
        "time_sensitivity": int(round(_clamp_score_1_5(obj.get("time_sensitivity"), 3.0))),
        "is_rumor": bool(obj.get("is_rumor")),
    }


def _resolve_ai_impact(
    obj: dict[str, Any],
    *,
    freshness: str,
) -> tuple[ImpactLevel, dict[str, Any] | None, str]:
    """返回 (ai 客观档, 因子 dict 或 None, rationale)。"""
    rationale = str(obj.get("rationale") or "").strip()
    factors = _parse_impact_factors(obj)
    if factors is not None:
        return synthesize_ai_impact_level(factors, freshness=freshness), factors, rationale
    # 兼容旧模型输出：直接给 impact_level
    legacy = str(obj.get("impact_level") or "medium")
    if legacy not in _IMPACT:
        legacy = "medium"
    return legacy, None, rationale  # type: ignore[return-value]


def _parse_llm_patch(obj: dict[str, Any], *, raw: RawMessage, analyzed: AnalyzedMessage) -> dict[str, Any]:
    """将 AI 结构化字段融合进已有数据；detail/marks/生效时间等不由 AI 改写。"""
    summary = str(obj.get("summary") or analyzed.summary or raw.title or raw.content[:120]).strip()
    if len(summary) > 120:
        summary = summary[:117] + "…"
    freshness = str(obj.get("freshness") or analyzed.freshness or "new")
    if freshness not in _FRESHNESS:
        freshness = analyzed.freshness if analyzed.freshness in _FRESHNESS else "new"
    effect = str(obj.get("effect_status") or analyzed.effect_status or "not_erupted")
    if effect not in _EFFECT:
        effect = analyzed.effect_status if analyzed.effect_status in _EFFECT else "not_erupted"
    ai_level, factors, rationale = _resolve_ai_impact(obj, freshness=freshness)
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
    # 工作档 = AI 客观档经关注升档；ai_impact_level 保持客观档
    working = initial_impact_with_follow(
        ai_level,
        title=title,
        summary=summary,
        detail=detail,
        keywords=keywords,
        targets=targets,
    )
    patch: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "detail": detail,
        "keywords": keywords,
        "url": url,
        "targets": targets,
        "ai_impact_level": ai_level,
        "impact_level": working,
        "impact_factors": factors,
        "impact_rationale": rationale,
        "freshness": freshness,
        "effect_status": effect,
        "status": "draft",
        "analyzed_by": "ai",
    }
    return patch


def _parse_impact_only_patch(
    obj: dict[str, Any],
    *,
    raw: RawMessage,
    analyzed: AnalyzedMessage,
) -> dict[str, Any]:
    """仅重算 AI 影响档；不改标题/摘要/标的/新旧/炒作等。"""
    freshness = analyzed.freshness if analyzed.freshness in _FRESHNESS else "new"
    ai_level, factors, rationale = _resolve_ai_impact(obj, freshness=freshness)
    title = analyzed.title or raw.title or ""
    summary = analyzed.summary or ""
    detail = analyzed.detail or raw.content or ""
    keywords = list(analyzed.keywords) or list(raw.keywords)
    targets = _existing_targets(raw, analyzed)
    working = initial_impact_with_follow(
        ai_level,
        title=title,
        summary=summary,
        detail=detail,
        keywords=keywords,
        targets=targets,
    )
    return {
        "ai_impact_level": ai_level,
        "impact_level": working,
        "impact_factors": factors,
        "impact_rationale": rationale,
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


def analyze_one(
    cfg: dict,
    *,
    raw_id: str | None = None,
    analyzed_id: str | None = None,
    mode: str = "full",
) -> AnalyzedMessage:
    """mode=full 全量结构化分析；mode=impact 仅重算 AI 影响档。"""
    mode_s = str(mode or "full").strip().lower()
    if mode_s not in ("full", "impact"):
        raise ValueError("mode 仅支持 full 或 impact")

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
    system = IMPACT_SYSTEM if mode_s == "impact" else SYSTEM
    skeleton = IMPACT_JSON_SKELETON if mode_s == "impact" else JSON_SKELETON
    last_err = ""
    obj: dict[str, Any] | None = None
    for attempt in range(2):
        text = _llm_complete(
            cfg,
            user,
            retry_hint=last_err if attempt else "",
            system=system,
            skeleton=skeleton,
        )
        obj = extract_first_json(text)
        if obj:
            break
        last_err = "未找到 JSON 对象"
    if not obj:
        raise RuntimeError("模型未返回可解析的 JSON")

    if mode_s == "impact":
        patch = _parse_impact_only_patch(obj, raw=raw, analyzed=analyzed)
    else:
        patch = _parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    # 已手动指定优先级时，AI 仍写 ai_impact_level，但不再改写工作档
    if analyzed.impact_manual:
        patch.pop("impact_level", None)
    updated = store.update_analyzed(analyzed.id, patch)
    if not updated:
        raise RuntimeError("写入分析结果失败")
    _emit_message_analyzed_hook(updated)
    return updated


def _emit_message_analyzed_hook(analyzed: AnalyzedMessage) -> None:
    """分析结果落盘后通知插件（宿主未合并时静默跳过）。"""
    try:
        from duanxian import hooks
    except ImportError:
        return
    try:
        dump = analyzed.model_dump() if hasattr(analyzed, "model_dump") else dict(analyzed)
        hooks.RUNNER.emit_message_analyzed(dump)
    except Exception:  # noqa: BLE001
        pass


def run_batch_stream(
    cfg: dict,
    *,
    raw_ids: list[str],
    analyzed_ids: list[str],
    mode: str = "full",
):
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
                result = analyze_one(cfg, raw_id=tid, mode=mode)
            else:
                result = analyze_one(cfg, analyzed_id=tid, mode=mode)
            ok += 1
            yield {"type": "item", "data": result.model_dump()}
        except Exception as e:  # noqa: BLE001
            yield {"type": "item_error", "id": tid, "message": str(e)[:500]}
    yield {"type": "done", "total": total, "ok": ok, "failed": total - ok}
