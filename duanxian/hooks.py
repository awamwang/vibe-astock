"""插件钩子 —— 数据暴露（引擎 push 回调）与数据导入（插件调 HookRegistry）。

本地插件：`~/.vibe-astock/hooks_local.py` 导出 `PACK`（HookPack 实例）。
也可用环境变量 `VIBE_ASTOCK_HOOKS` 指向任意 .py 路径。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import hook_schemas as hs
from .util import china_now

_LOCAL_HOOKS_PATH = os.path.expanduser("~/.vibe-astock/hooks_local.py")

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


EMPTY_PACK = HookPack(name="builtin", version="0.0.0", schema_bundle="vibe.hooks/builtin")


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


def _local_hooks_path() -> str | None:
    env = os.environ.get("VIBE_ASTOCK_HOOKS", "").strip()
    if env.lower() in {"builtin", "default", "none"}:
        return None
    if env:
        return os.path.expanduser(env)
    return _LOCAL_HOOKS_PATH if os.path.isfile(_LOCAL_HOOKS_PATH) else None


def load_pack() -> HookPack:
    path = _local_hooks_path()
    if path is None:
        return EMPTY_PACK
    if not os.path.isfile(path):
        print(f"⚠️ 钩子包不存在，回退内置空包：{path}")
        return EMPTY_PACK
    print(f"⚙️ 加载本地钩子包（以进程权限执行，仅限可信文件）：{path}")
    mod_name = "vibe_astock_hooks_local"
    try:
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
            raise TypeError(f"{path} 里的 PACK 不是 HookPack 实例")
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(mod_name, None)
        print(f"⚠️ 钩子包加载失败，回退内置空包（{type(exc).__name__}: {exc}）")
        return EMPTY_PACK
    print(f"ℹ️ 已加载本地钩子包：{pack.name} v{pack.version}（{path}）")
    return pack


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


def _envelope(event: str, date: str, payload: dict, pack: HookPack) -> dict:
    now = china_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    if len(now) > 5 and now[-5] in "+-":
        now = f"{now[:-2]}:{now[-2:]}"
    return {
        "$schema": hs.ENVELOPE,
        "schema_version": hs.SCHEMA_VERSION,
        "event": event,
        "date": date,
        "emitted_at": now,
        "engine_version": hs.ENGINE_VERSION,
        "plugin": {"name": pack.name, "version": pack.version, "schema_bundle": pack.schema_bundle},
        "payload": payload,
    }


def _ctx(date: str, event: str, pack: HookPack) -> HookContext:
    now = china_now().strftime("%Y-%m-%dT%H:%M:%S%z")
    return HookContext(
        date=date,
        event=event,
        emitted_at=now,
        engine_version=hs.ENGINE_VERSION,
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
    def __init__(self, pack: HookPack, registry: HookRegistry):
        self.pack = pack
        self.registry = registry

    def emit_metrics(self, date: str, review: dict | None, *, scope: str = "review") -> None:
        payload = build_metrics_payload(scope, date, review)
        _safe_call(self.pack.on_metrics_snapshot, _ctx(date, "metrics.snapshot", self.pack),
                   _envelope("metrics.snapshot", date, payload, self.pack))

    def emit_budget(self, date: str, budget_env: dict) -> None:
        payload = build_budget_payload(budget_env)
        _safe_call(self.pack.on_budget_snapshot, _ctx(date, "budget.snapshot", self.pack),
                   _envelope("budget.snapshot", date, payload, self.pack))

    def emit_verification(self, date: str, review: dict) -> None:
        payload = build_verification_payload(date, review)
        _safe_call(self.pack.on_verification_snapshot, _ctx(date, "verification.snapshot", self.pack),
                   _envelope("verification.snapshot", date, payload, self.pack))

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
        if not self.pack.enable_review_saved:
            return
        mp = metrics_payload or build_metrics_payload("review", date, review)
        vp = verification_payload or build_verification_payload(date, review)
        bp = budget_payload
        if bp is None and budget_env is not None:
            bp = build_budget_payload(budget_env)
        inner = {
            "$schema": hs.REVIEW_SAVED,
            "schema_version": hs.SCHEMA_VERSION,
            "date": date,
            "review": review,
            "metrics": mp,
            "verification": vp,
            "budget": bp,
        }
        _safe_call(self.pack.on_review_saved, _ctx(date, "review.saved", self.pack),
                   _envelope("review.saved", date, inner, self.pack))

    def emit_after_review(self, date: str, review: dict, budget_env: dict | None) -> None:
        """复盘保存后按序派发：metrics → verification → budget → review.saved。"""
        if self.pack is EMPTY_PACK:
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


def _init() -> tuple[HookPack, HookRegistry, HookRunner]:
    pack = load_pack()
    registry = HookRegistry()
    if pack.on_register is not None:
        try:
            pack.on_register(registry)
        except Exception:  # noqa: BLE001
            print(f"⚠️ 钩子 on_register 失败：\n{traceback.format_exc()}")
    providers = _validate_providers(pack.metric_providers)
    if providers:
        from . import verification as vf

        vf.register_plugin_metrics(providers)
    runner = HookRunner(pack, registry)
    return pack, registry, runner


PACK, REGISTRY, RUNNER = _init()
