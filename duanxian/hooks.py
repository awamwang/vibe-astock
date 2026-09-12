"""插件钩子 —— 数据暴露（引擎 push 回调）与数据导入（插件调 HookRegistry）。

多插件：先用 `python -m duanxian.plugin_cli register <path>` 注册，
启用/停用/卸载见 `python -m duanxian.plugin_cli --help`。
注册表：`~/.vibe-astock/plugins.json`。
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from . import hook_schemas as hs
from .util import china_now, china_today

_BUILTIN_METRIC_PATHS: dict[str, tuple[str, ...]] = {
    "limit_up_count": ("emotion_metrics", "promotion", "limit_up_count"),
    "highest_board": ("emotion_metrics", "ladder_gap", "highest"),
    "promotion_1to2": ("emotion_metrics", "promotion", "tiers", "1进2", "rate"),
    "money_effect_median": ("emotion_metrics", "money_effect", "median"),
    "broken_rate": ("market_facts", "seal_quality", "broken_rate"),
    "never_broken_rate": ("market_facts", "seal_quality", "never_broken_rate"),
    "deep_loss_count": ("market_facts", "loss_effect", "deep_loss_5_count"),
    "theme_concentration": ("market_facts", "theme_structure", "concentration"),
    "market_limit_down": ("market_facts", "loss_effect", "market_limit_down"),
}


@dataclass(frozen=True)
class ImportResult:
    ok: bool
    kind: str
    detail: str = ""


@dataclass(frozen=True)
class HookContext:
    date: str
    event: str
    emitted_at: str
    engine_version: str
    plugin_id: str
    plugin_name: str
    plugin_version: str


@dataclass(frozen=True)
class MetricProvider:
    """可验证指标注册项；暴露面与验证面共用同一 key。"""

    key: str
    label: str
    hint: str
    eps: float
    getter: Callable[[dict, dict], Optional[float]]
    higher_is_hotter: bool = True
    unit: str = ""
    schema_id: str | None = None
    scopes: frozenset[str] = frozenset({"review"})
    register_in: frozenset[str] = frozenset({"verification_menu", "export_index"})
    path: tuple[str, ...] | None = None


@dataclass(frozen=True)
class HookPack:
    name: str
    version: str
    schema_bundle: str
    metric_providers: tuple[MetricProvider, ...] = ()
    on_register: Callable[["HookRegistry"], None] | None = None
    on_enable: Callable[["HookRegistry"], None] | None = None
    on_disable: Callable[[], None] | None = None
    on_metrics_snapshot: Callable[[HookContext, dict], None] | None = None
    on_live_snapshot: Callable[[HookContext, dict], None] | None = None
    on_budget_snapshot: Callable[[HookContext, dict], None] | None = None
    on_verification_snapshot: Callable[[HookContext, dict], None] | None = None
    on_review_saved: Callable[[HookContext, dict], None] | None = None
    on_watchlist_add: Callable[[HookContext, dict], None] | None = None
    on_watchlist_change: Callable[[HookContext, dict], None] | None = None
    on_message_analyzed: Callable[[HookContext, dict], None] | None = None
    enable_review_saved: bool = True


@dataclass(frozen=True)
class LoadedPlugin:
    id: str
    path: str
    pack: HookPack


class HookRegistry:
    """插件写入引擎的唯一入口。"""

    def __init__(self) -> None:
        self._bound_plugin_id: str | None = None

    @property
    def plugin_id(self) -> str | None:
        """当前绑定的注册表 id（`on_register` 内可用）。"""
        return self._bound_plugin_id

    def bind_plugin(self, plugin_id: str) -> None:
        self._bound_plugin_id = str(plugin_id)

    def unbind_plugin(self) -> None:
        self._bound_plugin_id = None

    def report_status(self, level: str, message: str, detail: str | None = None) -> None:
        """向引擎上报运行状态，供插件管理页展示。"""
        from . import plugin_status as ps

        pid = self._bound_plugin_id
        if not pid:
            raise RuntimeError("report_status 需在 on_register 内调用，或先 bind_plugin")
        ps.set_status(pid, level, message, detail)

    def report_current_stock(self, payload: dict) -> ImportResult:
        """上报插件侧当前股票（如同花顺焦点股）；代码未变时仍返回 ok。"""
        from . import current_stock as cs

        pid = self._bound_plugin_id
        if not pid:
            raise RuntimeError("report_current_stock 需在 on_enable 内调用，或先 bind_plugin")
        try:
            rec = cs.report(pid, payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if rec is None:
            return ImportResult(True, "current_stock", "unchanged")
        return ImportResult(True, "current_stock", rec.code)

    def import_portfolio(self, payload: dict) -> ImportResult:
        from . import screenshot_parse as sp

        body = dict(payload or {})
        body.setdefault("replace", True)
        try:
            _, _, holdings, replace, _fields = sp.validate_apply_payload(body)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if not replace:
            raise ValueError("钩子导入持仓仅支持全量覆盖（replace=true）")
        import portfolio as pf

        pf.replace_holdings(holdings)
        return ImportResult(True, "portfolio", f"{len(holdings)} 笔")

    def import_account(self, payload: dict) -> ImportResult:
        from . import trade_store as ts

        body = dict(payload or {})
        note = str(body.get("note") or "")
        fields = body.get("account_fields")
        if not isinstance(fields, dict):
            fields = {}
        extra = {k: body[k] for k in body if k in ts._ACCOUNT_FIELD_KEYS}  # noqa: SLF001
        merged_fields = {**fields, **extra}

        if body.get("equity") is not None and body.get("equity") != "":
            eq = float(body["equity"])
            if eq < 0:
                raise ValueError("权益不能为负")
            if not note.strip() and merged_fields:
                note = ts.format_account_summary(merged_fields)
            ts.set_equity(eq, note, fields=merged_fields or None)
        elif merged_fields or note:
            cur = ts.load_account()
            eq = cur.get("equity")
            if eq is not None:
                ts.set_equity(float(eq), note, fields=merged_fields or None)
            elif merged_fields:
                ts.set_account_fields(merged_fields, note=note or None)

        constants = body.get("constants")
        if isinstance(constants, dict) and constants:
            allowed = {k: v for k, v in constants.items() if v is not None}
            if allowed:
                ts.set_constants(**allowed)

        return ImportResult(True, "account", "已更新")

    def override_budget_phase(self, date: str, phase: str, reason: str = "") -> None:
        from . import trade_store as ts

        ts.set_override(str(date), phase, reason)

    def import_watchlist(self, payload: dict) -> ImportResult:
        body = dict(payload or {})
        raw = body.get("codes")
        if raw is None and "watchlist" in body:
            raw = body.get("watchlist")
        _ensure_vr_path()
        import watchlist as wl  # noqa: PLC0415
        import watchtower as wt  # noqa: PLC0415

        try:
            clean = wl.normalize_codes(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

        if body.get("merge"):
            source = str(body.get("source") or "插件：未知").strip() or "插件：未知"
            out = wl.merge_plugin_codes(clean, source)
        else:
            body.setdefault("replace", True)
            if not body.get("replace"):
                raise ValueError("钩子导入自选股须 replace=true 全量覆盖，或 merge=true 按来源合并")
            default_source = str(body.get("source") or wl.SOURCE_MANUAL).strip() or wl.SOURCE_MANUAL
            out = wl.replace_codes(clean, default_source=default_source)

        codes = out.get("codes") or []
        wt.set_watch(codes)
        wt.poke()
        return ImportResult(True, "watchlist", f"{len(codes)} 只")

    def register_message_source(self, source_id: str, label: str = "") -> ImportResult:
        """登记插件消息源（进程内）；停用插件时自动注销。"""
        from . import message_sources as ms

        pid = self._bound_plugin_id
        if not pid:
            raise RuntimeError("register_message_source 需在 on_enable 内调用，或先 bind_plugin")
        try:
            rec = ms.register(pid, source_id, label)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return ImportResult(True, "message_source", rec.source_id)

    def push_messages(self, payload: dict) -> ImportResult:
        """按标准格式推送消息入库；默认仅 raw，auto_analyze=true 时顺带生成 analyzed。"""
        from . import hook_schemas as hs
        from . import message_sources as ms

        pid = self._bound_plugin_id
        if not pid:
            raise RuntimeError("push_messages 需在 on_enable 内调用，或先 bind_plugin")

        body = dict(payload or {})
        schema = str(body.get("$schema") or "").strip()
        if schema and schema != hs.MESSAGE_PUSH and not schema.endswith("/message-push/1.0.0"):
            raise ValueError(f"不支持的消息推送 schema: {schema}")

        source_id = str(body.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source_id 不能为空")
        rec = ms.require_owned(source_id, pid)

        raw_msgs = body.get("messages")
        if not isinstance(raw_msgs, list) or not raw_msgs:
            raise ValueError("messages 须为非空列表")

        auto_analyze = bool(body.get("auto_analyze"))
        _ensure_vr_path()
        drafts, analyze_items = _parse_message_push_items(
            raw_msgs,
            source_id=rec.source_id,
            source_label=rec.label,
        )
        if not drafts:
            raise ValueError("messages 中无有效条目（content 不能为空）")

        from message import store as msg_store  # noqa: PLC0415

        inserted = msg_store.insert_raw_batch(drafts)
        analyzed_n = 0
        analyzed_rows: list[dict] = []
        if auto_analyze and inserted:
            by_ext: dict[str, dict] = {}
            by_content: dict[str, dict] = {}
            for item in analyze_items:
                ext = str(item.get("external_ref") or "").strip()
                content = str(item.get("content") or "").strip()
                if ext:
                    by_ext[ext] = item
                if content and content not in by_content:
                    by_content[content] = item
            for raw in inserted:
                item = None
                if raw.external_ref and raw.external_ref in by_ext:
                    item = by_ext[raw.external_ref]
                else:
                    item = by_content.get(raw.content)
                patch = _analyze_patch_from_push_item(item or {}, raw)
                analyzed = msg_store.upsert_analyzed_from_raw(raw, patch=patch, analyzed_by="rule")
                analyzed_n += 1
                if analyzed is not None:
                    dump = analyzed.model_dump() if hasattr(analyzed, "model_dump") else dict(analyzed)
                    analyzed_rows.append(dump)

        if analyzed_rows:
            try:
                # 模块级 RUNNER 在 _init 后可用；测试里可直接构造 HookRunner
                runner = globals().get("RUNNER")
                if runner is not None:
                    runner.emit_message_analyzed_batch(analyzed_rows)
            except Exception:  # noqa: BLE001
                traceback.print_exc()

        return ImportResult(
            True,
            "message_push",
            f"inserted={len(inserted)} analyzed={analyzed_n}",
        )

    def import_experience(self, payload: dict) -> ImportResult:
        """写入交易经验主题（对齐 POST /api/experience/commit）。"""
        from . import experience as exp

        body = dict(payload or {})
        schema = str(body.get("$schema") or "").strip()
        if schema and schema != hs.EXPERIENCE_IMPORT and not schema.endswith("/experience-import/1.0.0"):
            raise ValueError(f"不支持的经验写入 schema: {schema}")
        files = body.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("files 须为非空列表")
        result = exp.commit_files(files)
        written = result.get("written") or []
        return ImportResult(True, "experience", f"{len(written)} 篇")

    def push_article(self, payload: dict) -> ImportResult:
        """写入研报文章（对齐 POST /api/articles/commit）；可传 files[] 或单篇字段。"""
        from . import articles as arts

        body = dict(payload or {})
        schema = str(body.get("$schema") or "").strip()
        if schema and schema != hs.ARTICLE_PUSH and not schema.endswith("/article-push/1.0.0"):
            raise ValueError(f"不支持的文章推送 schema: {schema}")
        files = body.get("files")
        if files is None:
            # 单篇：顶层 title/original/content 等
            if any(k in body for k in ("title", "original", "content", "filename")):
                files = [body]
            else:
                files = []
        if not isinstance(files, list) or not files:
            raise ValueError("files 须为非空列表，或提供单篇 title/original")
        result = arts.commit_files(files)
        written = result.get("written") or []
        return ImportResult(True, "article", f"{len(written)} 篇")


def _parse_message_push_items(
    items: list[Any],
    *,
    source_id: str,
    source_label: str,
) -> tuple[list[Any], list[dict]]:
    """将标准推送条目转为 RawMessageDraft 列表，并保留原 dict 供 auto_analyze。"""
    import uuid

    from message.schemas import ImpactTarget, RawMessageDraft  # noqa: PLC0415

    drafts: list[Any] = []
    kept: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "").strip()
        if not content:
            continue
        title = str(raw.get("title") or "").strip()
        kw_raw = raw.get("keywords")
        keywords = kw_raw if isinstance(kw_raw, list) else ([str(kw_raw)] if kw_raw else [])
        marks_raw = raw.get("marks")
        marks = marks_raw if isinstance(marks_raw, list) else ([str(marks_raw)] if marks_raw else [])
        ext = str(raw.get("external_ref") or "").strip() or None
        produced = str(raw.get("produced_at") or "").strip() or None
        eff_mode = str(raw.get("effective_mode") or "immediate").strip() or "immediate"
        if eff_mode not in ("immediate", "scheduled"):
            eff_mode = "immediate"
        eff_at = str(raw.get("effective_at") or "").strip() or None
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        targets: list[Any] = []
        _valid_kinds = {"market", "sector", "theme", "stock", "other"}
        for t in raw.get("targets") or []:
            if isinstance(t, dict) and str(t.get("name") or "").strip():
                kind = str(t.get("kind") or "other")
                if kind not in _valid_kinds:
                    kind = "other"
                targets.append(
                    ImpactTarget(
                        kind=kind,  # type: ignore[arg-type]
                        code=t.get("code"),
                        name=str(t.get("name") or ""),
                    )
                )
        drafts.append(
            RawMessageDraft(
                draft_key=f"draft_{uuid.uuid4().hex[:8]}",
                source_id=source_id,
                source_label=source_label,
                content=content,
                title=title or content.split("\n", 1)[0][:120],
                keywords=[str(k) for k in keywords],
                url=str(raw.get("url") or ""),
                marks=[str(m) for m in marks],
                external_ref=ext,
                produced_at=produced,
                effective_mode=eff_mode,  # type: ignore[arg-type]
                effective_at=eff_at,
                targets=targets,
                meta={**meta, "format": "plugin_push"},
            )
        )
        kept.append(raw)
    return drafts, kept


def _analyze_patch_from_push_item(item: dict, raw: Any) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "title": str(item.get("title") or raw.title or ""),
        "summary": str(item.get("summary") or "").strip()
        or (raw.title[:120] if raw.title else raw.content[:120]),
        "detail": str(item.get("detail") or "").strip() or raw.content,
        "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else list(raw.keywords),
        "url": str(item.get("url") or raw.url or ""),
        "marks": item.get("marks") if isinstance(item.get("marks"), list) else list(raw.marks),
    }
    if item.get("impact_level"):
        patch["impact_level"] = str(item["impact_level"])
    if item.get("effective_mode") in ("immediate", "scheduled"):
        patch["effective_mode"] = item["effective_mode"]
    if item.get("effective_at"):
        patch["effective_at"] = str(item["effective_at"])
    targets = item.get("targets")
    if isinstance(targets, list):
        patch["targets"] = [
            {
                "kind": t.get("kind") or "other",
                "code": t.get("code"),
                "name": str(t.get("name") or ""),
            }
            for t in targets
            if isinstance(t, dict) and str(t.get("name") or "").strip()
        ]
    elif raw.meta.get("_targets_json"):
        patch["targets"] = raw.meta["_targets_json"]
    return patch


def _ensure_vr_path() -> None:
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vr_dir = os.path.join(root, "vr")
    if os.path.isdir(vr_dir) and vr_dir not in sys.path:
        sys.path.insert(0, vr_dir)


def _module_name(plugin_id: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in plugin_id)
    return f"vibe_astock_plugin_{safe}"


def load_pack_from_path(path: str, *, plugin_id: str) -> HookPack:
    """从单个 .py 文件加载 PACK。"""
    mod_name = _module_name(plugin_id)
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    pack = getattr(module, "PACK", None)
    if not isinstance(pack, HookPack):
        sys.modules.pop(mod_name, None)
        raise TypeError(f"{path} 里的 PACK 不是 HookPack 实例")
    return pack


def load_plugins() -> list[LoadedPlugin]:
    """从注册表加载所有已启用插件。"""
    from . import plugin_store as ps

    loaded: list[LoadedPlugin] = []
    for pid, path in ps.list_enabled_paths():
        try:
            pack = load_pack_from_path(path, plugin_id=pid)
        except Exception as exc:  # noqa: BLE001
            from . import plugin_status as ps

            print(f"⚠️ 插件加载失败（id={pid}）：{type(exc).__name__}: {exc}")
            ps.set_status(pid, "error", "加载失败", f"{type(exc).__name__}: {exc}")
            continue
        print(f"ℹ️ 已加载插件：{pack.name} v{pack.version}（id={pid}）")
        loaded.append(LoadedPlugin(id=pid, path=path, pack=pack))
    return loaded


def _wrap_source(data: Any, as_of: str, *, is_live: bool = False) -> dict:
    available = True
    reason = None
    if isinstance(data, dict):
        available = bool(data.get("available", True))
        reason = data.get("reason")
    return {
        "available": available,
        "as_of": as_of,
        "is_live": is_live,
        "reason": reason,
        "data": data if isinstance(data, dict) else data,
    }


def _metric_index(scope: str) -> list[dict]:
    from . import verification as vf

    out: list[dict] = []
    for m in vf.metrics_for_export():
        scopes = getattr(m, "scopes", frozenset({"review"}))
        if scope not in scopes and "both" not in scopes:
            continue
        path = getattr(m, "path", None) or _BUILTIN_METRIC_PATHS.get(m.key)
        entry: dict[str, Any] = {
            "key": m.key,
            "label": m.label,
            "unit": m.unit,
            "scope": scope,
            "verifiable": True,
        }
        if path:
            entry["path"] = list(path)
        out.append(entry)
    return out


def build_metrics_payload(
    scope: str,
    date: str,
    review: dict | None = None,
) -> dict:
    sources: dict[str, Any] = {}
    if scope == "review" and review:
        sources["emotion_metrics"] = _wrap_source(review.get("emotion_metrics") or {}, date)
        sources["market_facts"] = _wrap_source(review.get("market_facts") or {}, date)
    if scope in ("live", "both"):
        try:
            from . import live_emotion as le

            snap = le.snapshot()
            as_of = str(snap.get("as_of") or date)
            sources["live_emotion"] = _wrap_source(snap, as_of, is_live=bool(snap.get("is_live")))
        except Exception as exc:  # noqa: BLE001
            sources["live_emotion"] = {
                "available": False,
                "as_of": date,
                "is_live": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "data": None,
            }
    if scope == "review":
        for mod_name, call in (
            ("short_board", lambda: __import__("duanxian.short_board", fromlist=["snapshot"]).snapshot()),
            ("breadth", lambda: __import__("duanxian.breadth", fromlist=["market_breadth"]).market_breadth(date)),
            ("mood_block", lambda: __import__("duanxian.mood_block", fromlist=["snapshot"]).snapshot()),
        ):
            key = "mood_blocks" if mod_name == "mood_block" else mod_name
            try:
                snap = call()
                sources[key] = _wrap_source(snap, date)
            except Exception as exc:  # noqa: BLE001
                sources[key] = {
                    "available": False,
                    "as_of": date,
                    "is_live": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "data": None,
                }
    return {
        "$schema": hs.METRICS_SNAPSHOT,
        "schema_version": hs.SCHEMA_VERSION,
        "scope": scope,
        "date": date,
        "sources": sources,
        "metric_index": _metric_index(scope),
    }


def build_budget_payload(budget_env: dict) -> dict:
    return {
        "$schema": hs.BUDGET_SNAPSHOT,
        "schema_version": hs.SCHEMA_VERSION,
        "date": budget_env.get("date"),
        "available": budget_env.get("available"),
        "reason": budget_env.get("reason"),
        "phase": budget_env.get("phase"),
        "rule_phase": budget_env.get("rule_phase"),
        "override_phase": budget_env.get("override_phase"),
        "override_reason": budget_env.get("override_reason"),
        "cap_total_pct": budget_env.get("cap_total"),
        "cap_single_pct": budget_env.get("cap_single"),
        "prompt": budget_env.get("prompt"),
        "allow": budget_env.get("allow") or [],
        "forbid": budget_env.get("forbid") or [],
        "expansion_allowed": budget_env.get("expansion_allowed"),
        "demoted": budget_env.get("demoted"),
        "classify_reasons": budget_env.get("classify_reasons") or [],
        "width_divergence": budget_env.get("width_divergence"),
        "repair_proxy": budget_env.get("repair_proxy"),
        "block_new_long_reasons": budget_env.get("block_new_long_reasons") or [],
    }


def build_verification_payload(date: str, review: dict) -> dict:
    from . import verification as vf

    focus = review.get("focus") or {}
    ai_items = focus.get("verification_items") or []
    merged = vf.merged_items(date, ai_items)
    items = vf.describe_items(
        merged,
        review.get("emotion_metrics") or {},
        review.get("market_facts") or {},
    )
    return {
        "$schema": hs.VERIFICATION_SNAPSHOT,
        "schema_version": hs.SCHEMA_VERSION,
        "date": date,
        "items": items,
    }


def build_watchlist_add_payload(
    codes: list[str],
    *,
    source: str = "手动添加",
    name: str | None = None,
) -> dict:
    """构造 watchlist.add 事件 payload。"""
    clean = [str(c).strip() for c in codes if str(c or "").strip()]
    body: dict[str, Any] = {
        "$schema": hs.WATCHLIST_ADD,
        "schema_version": hs.SCHEMA_VERSION,
        "codes": clean,
        "source": str(source or "手动添加").strip() or "手动添加",
    }
    if name:
        body["name"] = str(name).strip()
    return body


def build_watchlist_change_payload(
    op: str,
    codes: list[str],
    *,
    source: str = "手动添加",
    name: str | None = None,
    added: list[str] | None = None,
    removed: list[str] | None = None,
) -> dict:
    """构造 watchlist.change 事件 payload（op=add|remove|replace）。"""
    op_s = str(op or "").strip().lower()
    if op_s not in ("add", "remove", "replace"):
        raise ValueError("op 仅支持 add / remove / replace")
    clean = [str(c).strip() for c in codes if str(c or "").strip()]
    body: dict[str, Any] = {
        "$schema": hs.WATCHLIST_CHANGE,
        "schema_version": hs.SCHEMA_VERSION,
        "op": op_s,
        "codes": clean,
        "source": str(source or "手动添加").strip() or "手动添加",
    }
    if name:
        body["name"] = str(name).strip()
    if added is not None:
        body["added"] = [str(c).strip() for c in added if str(c or "").strip()]
    if removed is not None:
        body["removed"] = [str(c).strip() for c in removed if str(c or "").strip()]
    return body


def _safe_live_source(key: str, date: str, fetch) -> dict:
    try:
        snap = fetch()
        if not isinstance(snap, dict):
            raise TypeError(f"{key} 返回非 dict")
        as_of = str(snap.get("as_of") or snap.get("date") or date)
        is_live = bool(snap.get("is_live", True))
        return _wrap_source(snap, as_of, is_live=is_live)
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "as_of": date,
            "is_live": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "data": None,
        }


def build_live_payload(date: str | None = None) -> dict:
    """构造随盘快照：打板情绪 / 环境条 / 昨涨停效应 / 连板榜分块保留（ADR-0001）。"""
    day = date or china_today()

    def _emotion():
        from . import live_emotion as le

        return le.snapshot()

    def _board():
        from . import short_board as sb

        return sb.snapshot()

    def _zt_effect():
        from . import live_zt_effect as lze

        return lze.snapshot()

    def _ladder():
        _ensure_vr_path()
        import market as mkt  # noqa: PLC0415

        return mkt.get_short_term_emotion()

    sources = {
        "live_emotion": _safe_live_source("live_emotion", day, _emotion),
        "short_board": _safe_live_source("short_board", day, _board),
        "live_zt_effect": _safe_live_source("live_zt_effect", day, _zt_effect),
        # 连板股客观榜（VR short_term_emotion）；与打板情绪 / 环境条分立
        "ladder": _safe_live_source("ladder", day, _ladder),
    }
    return {
        "$schema": hs.LIVE_SNAPSHOT,
        "schema_version": hs.SCHEMA_VERSION,
        "date": day,
        "sources": sources,
    }


def build_message_analyzed_payload(analyzed: dict) -> dict:
    """从分析消息 dict 抽出插件出站字段。"""
    body = dict(analyzed or {})
    targets_raw = body.get("targets") or []
    targets: list[dict] = []
    if isinstance(targets_raw, list):
        for t in targets_raw:
            if isinstance(t, dict) and str(t.get("name") or "").strip():
                targets.append({
                    "kind": str(t.get("kind") or "other"),
                    "code": t.get("code"),
                    "name": str(t.get("name") or ""),
                })
    return {
        "$schema": hs.MESSAGE_ANALYZED,
        "schema_version": hs.SCHEMA_VERSION,
        "id": str(body.get("id") or ""),
        "source_id": str(body.get("source_id") or ""),
        "source_label": str(body.get("source_label") or ""),
        "title": str(body.get("title") or ""),
        "summary": str(body.get("summary") or ""),
        "impact_level": str(body.get("impact_level") or "medium"),
        "ai_impact_level": body.get("ai_impact_level"),
        "initial_impact_level": body.get("initial_impact_level"),
        "freshness": str(body.get("freshness") or ""),
        "analyzed_by": body.get("analyzed_by"),
        "raw_ids": list(body.get("raw_ids") or []),
        "targets": targets,
        "matched_follow_keywords": list(body.get("matched_follow_keywords") or []),
        "matched_follow_blocks": list(body.get("matched_follow_blocks") or []),
    }


def _envelope(event: str, date: str, payload: dict, plugin: LoadedPlugin) -> dict:
    now = china_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    if len(now) > 5 and now[-5] in "+-":
        now = f"{now[:-2]}:{now[-2:]}"
    pack = plugin.pack
    return {
        "$schema": hs.ENVELOPE,
        "schema_version": hs.SCHEMA_VERSION,
        "event": event,
        "date": date,
        "emitted_at": now,
        "engine_version": hs.ENGINE_VERSION,
        "plugin": {
            "id": plugin.id,
            "name": pack.name,
            "version": pack.version,
            "schema_bundle": pack.schema_bundle,
        },
        "payload": payload,
    }


def _ctx(date: str, event: str, plugin: LoadedPlugin) -> HookContext:
    now = china_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    pack = plugin.pack
    return HookContext(
        date=date,
        event=event,
        emitted_at=now,
        engine_version=hs.ENGINE_VERSION,
        plugin_id=plugin.id,
        plugin_name=pack.name,
        plugin_version=pack.version,
    )


def _safe_call(
    fn: Callable[..., None] | None,
    plugin: LoadedPlugin | None,
    *args,
) -> None:
    if fn is None:
        return
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(f"⚠️ 钩子回调失败：\n{tb}")
        if plugin is not None:
            from . import plugin_status as ps

            ps.set_status(
                plugin.id,
                "warn",
                "钩子回调失败",
                tb,
            )


class HookRunner:
    def __init__(self, plugins: list[LoadedPlugin], registry: HookRegistry):
        self.plugins = list(plugins)
        self.registry = registry
        self._live_lock = threading.Lock()
        self._live_last_emit = 0.0
        self._live_min_interval = 15.0

    def emit_metrics(self, date: str, review: dict | None, *, scope: str = "review") -> None:
        payload = build_metrics_payload(scope, date, review)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_metrics_snapshot,
                lp,
                _ctx(date, "metrics.snapshot", lp),
                _envelope("metrics.snapshot", date, payload, lp),
            )

    def emit_live_snapshot(
        self,
        date: str | None = None,
        *,
        force: bool = False,
        min_interval: float | None = None,
        payload: dict | None = None,
    ) -> int:
        """向已实现 on_live_snapshot 的插件派发随盘快照；默认节流，返回收到回调的插件数。"""
        import time

        if not any(lp.pack.on_live_snapshot is not None for lp in self.plugins):
            return 0

        interval = self._live_min_interval if min_interval is None else float(min_interval)
        now = time.monotonic()
        with self._live_lock:
            if not force and interval > 0 and (now - self._live_last_emit) < interval:
                return 0
            self._live_last_emit = now

        day = date or china_today()
        body = payload or build_live_payload(day)
        n = 0
        for lp in self.plugins:
            if lp.pack.on_live_snapshot is None:
                continue
            n += 1
            _safe_call(
                lp.pack.on_live_snapshot,
                lp,
                _ctx(day, "live.snapshot", lp),
                _envelope("live.snapshot", day, body, lp),
            )
        return n

    def emit_budget(self, date: str, budget_env: dict) -> None:
        payload = build_budget_payload(budget_env)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_budget_snapshot,
                lp,
                _ctx(date, "budget.snapshot", lp),
                _envelope("budget.snapshot", date, payload, lp),
            )

    def emit_verification(self, date: str, review: dict) -> None:
        payload = build_verification_payload(date, review)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_verification_snapshot,
                lp,
                _ctx(date, "verification.snapshot", lp),
                _envelope("verification.snapshot", date, payload, lp),
            )

    def emit_review_saved(
        self,
        date: str,
        review: dict,
        budget_env: dict | None,
        *,
        metrics_payload: dict | None = None,
        verification_payload: dict | None = None,
        budget_payload: dict | None = None,
    ) -> None:
        mp = metrics_payload or build_metrics_payload("review", date, review)
        vp = verification_payload or build_verification_payload(date, review)
        bp = budget_payload
        if bp is None and budget_env is not None:
            bp = build_budget_payload(budget_env)
        for lp in self.plugins:
            if not lp.pack.enable_review_saved:
                continue
            inner = {
                "$schema": hs.REVIEW_SAVED,
                "schema_version": hs.SCHEMA_VERSION,
                "date": date,
                "review": review,
                "metrics": mp,
                "verification": vp,
                "budget": bp,
            }
            _safe_call(
                lp.pack.on_review_saved,
                lp,
                _ctx(date, "review.saved", lp),
                _envelope("review.saved", date, inner, lp),
            )

    def emit_after_review(self, date: str, review: dict, budget_env: dict | None) -> None:
        """复盘保存后按序派发：metrics → verification → budget → review.saved。"""
        if not self.plugins:
            return
        mp = build_metrics_payload("review", date, review)
        vp = build_verification_payload(date, review)
        bp = build_budget_payload(budget_env) if budget_env else None
        self.emit_metrics(date, review, scope="review")
        self.emit_verification(date, review)
        if budget_env is not None:
            self.emit_budget(date, budget_env)
        self.emit_review_saved(
            date, review, budget_env,
            metrics_payload=mp, verification_payload=vp, budget_payload=bp,
        )

    def emit_watchlist_add(
        self,
        codes: list[str],
        *,
        source: str = "手动添加",
        name: str | None = None,
        date: str | None = None,
    ) -> int:
        """向已实现 on_watchlist_add 的插件派发添加自选股事件；返回收到回调的插件数。"""
        clean = [str(c).strip() for c in codes if str(c or "").strip()]
        if not clean:
            return 0
        day = date or china_today()
        payload = build_watchlist_add_payload(clean, source=source, name=name)
        n = 0
        for lp in self.plugins:
            if lp.pack.on_watchlist_add is None:
                continue
            n += 1
            _safe_call(
                lp.pack.on_watchlist_add,
                lp,
                _ctx(day, "watchlist.add", lp),
                _envelope("watchlist.add", day, payload, lp),
            )
        return n

    def emit_watchlist_change(
        self,
        op: str,
        codes: list[str],
        *,
        source: str = "手动添加",
        name: str | None = None,
        added: list[str] | None = None,
        removed: list[str] | None = None,
        date: str | None = None,
    ) -> int:
        """向已实现 on_watchlist_change 的插件派发自选变更；返回收到回调的插件数。"""
        clean = [str(c).strip() for c in codes if str(c or "").strip()]
        op_s = str(op or "").strip().lower()
        if op_s not in ("add", "remove", "replace"):
            return 0
        if op_s != "replace" and not clean:
            return 0
        day = date or china_today()
        payload = build_watchlist_change_payload(
            op_s,
            clean,
            source=source,
            name=name,
            added=added,
            removed=removed,
        )
        n = 0
        for lp in self.plugins:
            if lp.pack.on_watchlist_change is None:
                continue
            n += 1
            _safe_call(
                lp.pack.on_watchlist_change,
                lp,
                _ctx(day, "watchlist.change", lp),
                _envelope("watchlist.change", day, payload, lp),
            )
        return n

    def emit_message_analyzed(self, analyzed: dict, *, date: str | None = None) -> int:
        """向已实现 on_message_analyzed 的插件派发单条分析结果。"""
        if not isinstance(analyzed, dict) or not analyzed.get("id"):
            return 0
        day = date or china_today()
        payload = build_message_analyzed_payload(analyzed)
        n = 0
        for lp in self.plugins:
            if lp.pack.on_message_analyzed is None:
                continue
            n += 1
            _safe_call(
                lp.pack.on_message_analyzed,
                lp,
                _ctx(day, "message.analyzed", lp),
                _envelope("message.analyzed", day, payload, lp),
            )
        return n

    def emit_message_analyzed_batch(
        self,
        rows: list[dict],
        *,
        date: str | None = None,
    ) -> int:
        """批量派发分析结果；返回累计回调次数（插件数 × 条数口径为逐条求和）。"""
        total = 0
        for row in rows or []:
            if isinstance(row, dict):
                total += self.emit_message_analyzed(row, date=date)
        return total


def _validate_providers(providers: tuple[MetricProvider, ...]) -> tuple[MetricProvider, ...]:
    from . import review_store as rs
    from . import verification as vf

    accepted: list[MetricProvider] = []
    sample_review = None
    for d in rs.dates()[:5]:
        sample_review = rs.load(d)
        if sample_review and sample_review.get("emotion_metrics"):
            break

    for p in providers:
        reg = set(p.register_in)
        if "export_index" in reg and "verification_menu" not in reg:
            print(f"⚠️ 指标 {p.key!r} 含 export_index 但缺 verification_menu，已跳过")
            continue
        if p.getter is None:
            print(f"⚠️ 指标 {p.key!r} 缺少 getter，已跳过")
            continue
        if "ai_pool" in reg:
            if sample_review is None:
                print(f"⚠️ 指标 {p.key!r} 进 ai_pool 但无复盘样本可 dry-run，已跳过")
                continue
            val = p.getter(
                sample_review.get("emotion_metrics") or {},
                sample_review.get("market_facts") or {},
            )
            if val is None:
                print(f"⚠️ 指标 {p.key!r} 在样本日 {sample_review.get('target_date')} 算不出值，已跳过")
                continue
        if p.key in vf.builtin_keys():
            print(f"⚠️ 指标 {p.key!r} 与内置 key 冲突，已跳过")
            continue
        accepted.append(p)
    return tuple(accepted)


def _unload_module(plugin_id: str) -> None:
    sys.modules.pop(_module_name(plugin_id), None)


def _find_loaded_plugin(plugins: list[LoadedPlugin], plugin_id: str) -> LoadedPlugin | None:
    for lp in plugins:
        if lp.id == plugin_id:
            return lp
    return None


def _activate_plugin(lp: LoadedPlugin, registry: HookRegistry) -> None:
    from . import plugin_status as ps

    registry.bind_plugin(lp.id)
    try:
        # 启动过程占位；on_enable 成功后若插件未另行上报，则恢复为「已加载」
        ps.set_status(lp.id, "info", ps.MSG_LOADING)
        activate_fn = lp.pack.on_enable or lp.pack.on_register
        if activate_fn is not None:
            try:
                activate_fn(registry)
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                print(f"⚠️ 插件 {lp.pack.name}（id={lp.id}）启用失败：\n{tb}")
                # RuntimeError 视为插件给出的可读说明，界面只展示文案，不全量堆栈
                msg = str(exc).strip() or "启用失败"
                detail = None if isinstance(exc, RuntimeError) else tb
                ps.set_status(lp.id, "error", msg, detail)
            else:
                st = ps.get_status(lp.id)
                # 插件未上报，或仍是引擎占位/旧错误时，标为已加载
                if (
                    st is None
                    or st.level in ("error", "off")
                    or ps.is_engine_transient(st)
                ):
                    ps.set_status(lp.id, "ok", "已加载")
        else:
            ps.set_status(lp.id, "ok", "已加载")
    finally:
        registry.unbind_plugin()


def _deactivate_plugin(lp: LoadedPlugin) -> None:
    from . import message_sources as ms
    from . import plugin_status as ps

    ms.unregister_plugin(lp.id)
    _safe_call(lp.pack.on_disable, lp)
    ps.set_status(lp.id, "off", "已停用")


def _collect_metric_providers(plugins: list[LoadedPlugin]) -> list[MetricProvider]:
    all_providers: list[MetricProvider] = []
    for lp in plugins:
        all_providers.extend(_validate_providers(lp.pack.metric_providers))
    return all_providers


def _rebuild_metric_providers(plugins: list[LoadedPlugin]) -> None:
    from . import verification as vf

    vf.reset_to_builtins()
    providers = _collect_metric_providers(plugins)
    if providers:
        vf.register_plugin_metrics(tuple(providers))


def apply_plugin_disable(plugin_id: str) -> bool:
    """运行时停用已加载插件（调用 on_disable 并从 RUNNER 移除）。"""
    lp = _find_loaded_plugin(PLUGINS, plugin_id)
    if lp is None:
        return False
    _deactivate_plugin(lp)
    PLUGINS[:] = [p for p in PLUGINS if p.id != plugin_id]
    RUNNER.plugins[:] = [p for p in RUNNER.plugins if p.id != plugin_id]
    _rebuild_metric_providers(PLUGINS)
    _unload_module(plugin_id)
    return True


def apply_plugin_enable(plugin_id: str) -> LoadedPlugin | None:
    """运行时启用插件（加载并调用 on_enable / on_register）。"""
    from . import plugin_status as ps
    from . import plugin_store as pstore

    _plugins_init_done.wait(timeout=120.0)

    if _find_loaded_plugin(PLUGINS, plugin_id) is not None:
        return _find_loaded_plugin(PLUGINS, plugin_id)

    rec = next((r for r in pstore.list_plugins() if r.id == plugin_id), None)
    if rec is None or not rec.enabled:
        return None

    path = str(Path(rec.path).expanduser().resolve())
    if not Path(path).is_file():
        ps.set_status(plugin_id, "error", "插件文件不存在", path)
        return None

    try:
        pack = load_pack_from_path(path, plugin_id=plugin_id)
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        print(f"⚠️ 插件加载失败（id={plugin_id}）：{err}")
        ps.set_status(plugin_id, "error", "加载失败", err)
        return None

    lp = LoadedPlugin(id=plugin_id, path=path, pack=pack)
    print(f"ℹ️ 已加载插件：{pack.name} v{pack.version}（id={plugin_id}）")
    _activate_plugin(lp, REGISTRY)
    PLUGINS.append(lp)
    RUNNER.plugins.append(lp)
    _rebuild_metric_providers(PLUGINS)
    return lp


def apply_plugin_restart(plugin_id: str) -> LoadedPlugin | None:
    """热重启已启用插件：停止运行时 → 卸载模块 → 重新加载并 on_enable。

    不改注册表 enabled；用于监督线程在报错后自动恢复。
    """
    from . import message_sources as ms
    from . import plugin_status as ps
    from . import plugin_store as pstore

    _plugins_init_done.wait(timeout=120.0)

    rec = next((r for r in pstore.list_plugins() if r.id == plugin_id), None)
    if rec is None or not rec.enabled:
        return None

    lp = _find_loaded_plugin(PLUGINS, plugin_id)
    if lp is not None:
        ms.unregister_plugin(lp.id)
        _safe_call(lp.pack.on_disable, lp)
        PLUGINS[:] = [p for p in PLUGINS if p.id != plugin_id]
        RUNNER.plugins[:] = [p for p in RUNNER.plugins if p.id != plugin_id]
        _rebuild_metric_providers(PLUGINS)
        _unload_module(plugin_id)

    ps.set_status(plugin_id, "info", ps.MSG_RESTARTING)
    print(f"ℹ️ 正在自动重启插件（id={plugin_id}）")
    return apply_plugin_enable(plugin_id)


def invoke_plugin_ensure_alive(*, plugin_id: str | None = None) -> list[str]:
    """调用已加载插件模块的按需自愈入口（ensure_bridge_alive / ensure_alive）。

    返回实际调用到的 plugin_id 列表。异常隔离，不影响其他插件。
    """
    called: list[str] = []
    targets = [lp for lp in PLUGINS if plugin_id is None or lp.id == plugin_id]
    for lp in targets:
        mod = sys.modules.get(_module_name(lp.id))
        if mod is None:
            continue
        fn = getattr(mod, "ensure_bridge_alive", None)
        if fn is None:
            fn = getattr(mod, "ensure_alive", None)
        if not callable(fn):
            continue
        try:
            fn()
            called.append(lp.id)
        except Exception:  # noqa: BLE001
            print(f"⚠️ 插件按需自愈失败 id={lp.id}")
            traceback.print_exc()
    return called


def _init() -> tuple[list[LoadedPlugin], HookRegistry, HookRunner]:
    plugins = load_plugins()
    registry = HookRegistry()
    for lp in plugins:
        _activate_plugin(lp, registry)
    _rebuild_metric_providers(plugins)
    runner = HookRunner(plugins, registry)
    return plugins, registry, runner


PLUGINS: list[LoadedPlugin] = []
REGISTRY = HookRegistry()
RUNNER = HookRunner(PLUGINS, REGISTRY)
_plugins_init_done = threading.Event()


def _init_plugins_background() -> None:
    global REGISTRY, RUNNER
    try:
        plugins, registry, runner = _init()
        PLUGINS[:] = plugins
        REGISTRY = registry
        RUNNER = runner
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    finally:
        _plugins_init_done.set()
        try:
            from . import plugin_supervisor as psup

            psup.ensure_started()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


threading.Thread(target=_init_plugins_background, name="hook-plugins-init", daemon=True).start()
