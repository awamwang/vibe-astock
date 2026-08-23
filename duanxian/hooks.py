"""插件钩子 —— 数据暴露（引擎 push 回调）与数据导入（插件调 HookRegistry）。

多插件：先用 `python -m duanxian.plugin_cli register <path>` 注册，
启用/停用/卸载见 `python -m duanxian.plugin_cli --help`。
注册表：`~/.vibe-astock/plugins.json`。
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import hook_schemas as hs
from .util import china_now

_BUILTIN_METRIC_PATHS: dict[str, tuple[str, ...]] = {
    "limit_up_count": ("emotion_metrics", "promotion", "limit_up_count"),
    "highest_board": ("emotion_metrics", "ladder_gap", "highest"),
    "promotion_1to2": ("emotion_metrics", "promotion", "tiers", "1进2", "rate"),
    "money_effect_median": ("emotion_metrics", "money_effect", "median"),
    "broken_rate": ("market_facts", "seal_quality", "broken_rate"),
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
    on_metrics_snapshot: Callable[[HookContext, dict], None] | None = None
    on_budget_snapshot: Callable[[HookContext, dict], None] | None = None
    on_verification_snapshot: Callable[[HookContext, dict], None] | None = None
    on_review_saved: Callable[[HookContext, dict], None] | None = None
    enable_review_saved: bool = True


@dataclass(frozen=True)
class LoadedPlugin:
    id: str
    path: str
    pack: HookPack


class HookRegistry:
    """插件写入引擎的唯一入口。"""

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
            print(f"⚠️ 插件加载失败（id={pid}）：{type(exc).__name__}: {exc}")
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


def _safe_call(fn: Callable[..., None] | None, *args) -> None:
    if fn is None:
        return
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        print(f"⚠️ 钩子回调失败：\n{traceback.format_exc()}")


class HookRunner:
    def __init__(self, plugins: list[LoadedPlugin], registry: HookRegistry):
        self.plugins = list(plugins)
        self.registry = registry

    def emit_metrics(self, date: str, review: dict | None, *, scope: str = "review") -> None:
        payload = build_metrics_payload(scope, date, review)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_metrics_snapshot,
                _ctx(date, "metrics.snapshot", lp),
                _envelope("metrics.snapshot", date, payload, lp),
            )

    def emit_budget(self, date: str, budget_env: dict) -> None:
        payload = build_budget_payload(budget_env)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_budget_snapshot,
                _ctx(date, "budget.snapshot", lp),
                _envelope("budget.snapshot", date, payload, lp),
            )

    def emit_verification(self, date: str, review: dict) -> None:
        payload = build_verification_payload(date, review)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_verification_snapshot,
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


def _init() -> tuple[list[LoadedPlugin], HookRegistry, HookRunner]:
    plugins = load_plugins()
    registry = HookRegistry()
    all_providers: list[MetricProvider] = []
    for lp in plugins:
        if lp.pack.on_register is not None:
            try:
                lp.pack.on_register(registry)
            except Exception:  # noqa: BLE001
                print(f"⚠️ 插件 {lp.pack.name}（id={lp.id}）on_register 失败：\n{traceback.format_exc()}")
        accepted = _validate_providers(lp.pack.metric_providers)
        all_providers.extend(accepted)
    if all_providers:
        from . import verification as vf

        vf.register_plugin_metrics(tuple(all_providers))
    runner = HookRunner(plugins, registry)
    return plugins, registry, runner


PLUGINS, REGISTRY, RUNNER = _init()
