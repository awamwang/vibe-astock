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
from pathlib import Path
from typing import Any, Callable, Optional

from . import hook_schemas as hs
from .util import china_now

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

    def emit_metrics(self, date: str, review: dict | None, *, scope: str = "review") -> None:
        payload = build_metrics_payload(scope, date, review)
        for lp in self.plugins:
            _safe_call(
                lp.pack.on_metrics_snapshot,
                lp,
                _ctx(date, "metrics.snapshot", lp),
                _envelope("metrics.snapshot", date, payload, lp),
            )

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
                if ps.get_status(lp.id) is None:
                    ps.set_status(lp.id, "ok", "已加载")
        else:
            ps.set_status(lp.id, "ok", "已加载")
    finally:
        registry.unbind_plugin()


def _deactivate_plugin(lp: LoadedPlugin) -> None:
    from . import plugin_status as ps

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


def _init() -> tuple[list[LoadedPlugin], HookRegistry, HookRunner]:
    from . import plugin_status as ps

    plugins = load_plugins()
    registry = HookRegistry()
    for lp in plugins:
        _activate_plugin(lp, registry)
    _rebuild_metric_providers(plugins)
    runner = HookRunner(plugins, registry)
    return plugins, registry, runner


PLUGINS, REGISTRY, RUNNER = _init()
