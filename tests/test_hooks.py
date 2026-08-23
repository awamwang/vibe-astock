"""插件钩子系统测试。"""

from __future__ import annotations

import json
import sys

import pytest


_HOOKS_SRC = '''
from __future__ import annotations
from duanxian.hooks import HookPack, HookRegistry, MetricProvider

_received = []

def on_register(reg: HookRegistry) -> None:
    global _reg
    _reg = reg

def on_metrics_snapshot(ctx, env):
    _received.append(("metrics", env["event"], env["payload"]["scope"]))

PACK = HookPack(
    name="test-hooks",
    version="1.0.0",
    schema_bundle="test/1",
    on_register=on_register,
    on_metrics_snapshot=on_metrics_snapshot,
)
'''


@pytest.mark.unit
class TestHookPackLoader:
    def test_load_local_pack(self, tmp_path, monkeypatch):
        import duanxian.hooks as hk

        p = tmp_path / "hooks_local.py"
        p.write_text(_HOOKS_SRC, encoding="utf-8")
        monkeypatch.setenv("VIBE_ASTOCK_HOOKS", str(p))
        sys.modules.pop("vibe_astock_hooks_local", None)

        pack = hk.load_pack()
        assert pack.name == "test-hooks"
        assert pack.version == "1.0.0"

    def test_broken_pack_falls_back(self, tmp_path, monkeypatch):
        import duanxian.hooks as hk

        p = tmp_path / "hooks_local.py"
        p.write_text("raise RuntimeError('boom')", encoding="utf-8")
        monkeypatch.setenv("VIBE_ASTOCK_HOOKS", str(p))
        sys.modules.pop("vibe_astock_hooks_local", None)

        assert hk.load_pack() is hk.EMPTY_PACK
        assert "vibe_astock_hooks_local" not in sys.modules


@pytest.mark.unit
class TestHookRegistryImport:
    def test_import_portfolio_replace(self, tmp_path, monkeypatch):
        from pathlib import Path

        vr_dir = str(Path(__file__).resolve().parents[1] / "vr")
        if vr_dir not in sys.path:
            sys.path.insert(0, vr_dir)
        import portfolio as pf

        from duanxian.hooks import HookRegistry

        pf_file = tmp_path / "portfolio.json"
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        pf_file.write_text(json.dumps({"holdings": [], "last_refresh": None}), encoding="utf-8")
        monkeypatch.setattr(pf, "PF_FILE", str(pf_file))
        monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))

        reg = HookRegistry()
        res = reg.import_portfolio({
            "holdings": [{"code": "600000", "shares": 100, "cost": 10.5}],
            "replace": True,
        })
        assert res.ok
        data = json.loads(pf_file.read_text(encoding="utf-8"))
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["code"] == "600000"


@pytest.mark.unit
class TestHookPayloads:
    def test_budget_payload_strips_readings(self):
        from duanxian.hooks import build_budget_payload

        out = build_budget_payload({
            "date": "2026-01-02",
            "available": True,
            "phase": "升温扩张",
            "cap_total": 0.6,
            "cap_single": 0.1,
            "readings": {"secret": 1},
            "classify_reasons": ["ok"],
        })
        assert out["cap_total_pct"] == 0.6
        assert "readings" not in out
        assert "secret" not in json.dumps(out)

    def test_metrics_payload_has_index(self):
        from duanxian.hooks import build_metrics_payload

        review = {
            "emotion_metrics": {"available": True, "promotion": {"limit_up_count": 40}},
            "market_facts": {"available": True},
        }
        out = build_metrics_payload("review", "2026-01-02", review)
        assert out["scope"] == "review"
        assert "emotion_metrics" in out["sources"]
        keys = {x["key"] for x in out["metric_index"]}
        assert "limit_up_count" in keys


@pytest.mark.unit
class TestHookRunner:
    def test_emit_after_review_order(self):
        from duanxian.hooks import HookPack, HookRunner, HookRegistry

        events: list[str] = []

        pack = HookPack(
            name="t",
            version="1.0.0",
            schema_bundle="t/1",
            on_metrics_snapshot=lambda c, e: events.append("metrics"),
            on_verification_snapshot=lambda c, e: events.append("verification"),
            on_budget_snapshot=lambda c, e: events.append("budget"),
            on_review_saved=lambda c, e: events.append("review"),
        )
        runner = HookRunner(pack, HookRegistry())
        review = {
            "target_date": "2026-01-02",
            "focus": {"verification_items": []},
            "emotion_metrics": {"available": True},
            "market_facts": {"available": True},
        }
        budget = {"date": "2026-01-02", "available": True, "phase": "升温扩张", "cap_total": 0.6}
        runner.emit_after_review("2026-01-02", review, budget)
        assert events == ["metrics", "verification", "budget", "review"]

    def test_callback_error_does_not_raise(self):
        from duanxian.hooks import HookPack, HookRunner, HookRegistry

        pack = HookPack(
            name="t",
            version="1.0.0",
            schema_bundle="t/1",
            on_metrics_snapshot=lambda c, e: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        runner = HookRunner(pack, HookRegistry())
        runner.emit_metrics("2026-01-02", {"emotion_metrics": {}, "market_facts": {}}, scope="review")


@pytest.mark.unit
class TestMetricProviderMerge:
    def test_register_plugin_metrics(self):
        from duanxian import verification as vf
        from duanxian.hooks import MetricProvider

        before = len(vf.METRICS)
        vf.register_plugin_metrics((
            MetricProvider(
                key="test_only_metric_xyz",
                label="T",
                hint="h",
                eps=1.0,
                getter=lambda m, f: 0.0,
                register_in=frozenset({"verification_menu"}),
            ),
        ))
        try:
            assert any(m.key == "test_only_metric_xyz" for m in vf.METRICS)
            assert "test_only_metric_xyz" in vf.known_metric_keys()
            assert any(m.key == "test_only_metric_xyz" for m in vf.metrics_for_menu())
            assert not any(m.key == "test_only_metric_xyz" for m in vf.metrics_for_ai_pool())
        finally:
            vf.METRICS[:] = vf.METRICS[:before]
            vf._rebuild_index()
