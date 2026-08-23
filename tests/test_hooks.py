"""插件钩子与注册表测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_PLUGIN_SRC = '''
from __future__ import annotations
from duanxian.hooks import HookPack, HookRegistry

def on_register(reg: HookRegistry) -> None:
    pass

PACK = HookPack(
    name="test-hooks",
    version="1.0.0",
    schema_bundle="test/1",
    on_register=on_register,
)
'''


@pytest.fixture
def plugin_home(tmp_path, monkeypatch):
    from duanxian import plugin_store as ps

    reg_dir = tmp_path / "vibe-astock"
    reg_dir.mkdir()
    monkeypatch.setattr(ps, "_USER_DIR", str(reg_dir))
    monkeypatch.setattr(ps, "_REGISTRY_FILE", str(reg_dir / "plugins.json"))
    return reg_dir


@pytest.mark.unit
class TestPluginStore:
    def test_register_list_enable_disable_uninstall(self, plugin_home):
        from duanxian import plugin_store as ps

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        rec = ps.register(str(p))
        assert rec.enabled
        assert rec.name == "test-hooks"
        assert len(ps.list_plugins()) == 1

        ps.set_enabled(rec.id, False)
        assert not ps.list_plugins(include_disabled=False)
        assert ps.list_plugins(include_disabled=True)[0].enabled is False

        ps.set_enabled(rec.id, True)
        hit = ps.uninstall(rec.id)
        assert hit.id == rec.id
        assert ps.list_plugins() == []

    def test_register_duplicate_path(self, plugin_home):
        from duanxian import plugin_store as ps

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        ps.register(str(p))
        with pytest.raises(ValueError, match="已注册"):
            ps.register(str(p))


@pytest.mark.unit
class TestHookPackLoader:
    def test_load_pack_from_path(self, plugin_home):
        from duanxian.hooks import load_pack_from_path

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        pack = load_pack_from_path(str(p), plugin_id="abc12345")
        assert pack.name == "test-hooks"

    def test_load_plugins_from_registry(self, plugin_home):
        from duanxian import plugin_store as ps
        from duanxian.hooks import load_plugins

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        rec = ps.register(str(p))
        loaded = load_plugins()
        assert len(loaded) == 1
        assert loaded[0].id == rec.id
        assert loaded[0].pack.name == "test-hooks"

    def test_disabled_plugin_not_loaded(self, plugin_home):
        from duanxian import plugin_store as ps
        from duanxian.hooks import load_plugins

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        rec = ps.register(str(p))
        ps.set_enabled(rec.id, False)
        assert load_plugins() == []


@pytest.mark.unit
class TestHookRegistryImport:
    def test_import_portfolio_replace(self, tmp_path, monkeypatch):
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


@pytest.mark.unit
class TestHookPayloads:
    def test_budget_payload_strips_readings(self):
        from duanxian.hooks import build_budget_payload

        out = build_budget_payload({
            "date": "2026-01-02",
            "available": True,
            "phase": "升温扩张",
            "cap_total": 0.6,
            "readings": {"secret": 1},
        })
        assert out["cap_total_pct"] == 0.6
        assert "readings" not in out

    def test_metrics_payload_has_index(self):
        from duanxian.hooks import build_metrics_payload

        review = {
            "emotion_metrics": {"available": True, "promotion": {"limit_up_count": 40}},
            "market_facts": {"available": True},
        }
        out = build_metrics_payload("review", "2026-01-02", review)
        keys = {x["key"] for x in out["metric_index"]}
        assert "limit_up_count" in keys


@pytest.mark.unit
class TestHookRunner:
    def test_emit_after_review_fans_out_to_multiple_plugins(self, plugin_home):
        from duanxian.hooks import HookPack, HookRunner, HookRegistry, LoadedPlugin

        events: list[str] = []

        def _pack(name: str) -> LoadedPlugin:
            return LoadedPlugin(
                id=name,
                path="/x",
                pack=HookPack(
                    name=name,
                    version="1.0.0",
                    schema_bundle="t/1",
                    on_metrics_snapshot=lambda c, e: events.append(f"{name}:metrics"),
                    on_review_saved=lambda c, e: events.append(f"{name}:review"),
                ),
            )

        runner = HookRunner([_pack("a"), _pack("b")], HookRegistry())
        review = {
            "focus": {"verification_items": []},
            "emotion_metrics": {"available": True},
            "market_facts": {"available": True},
        }
        runner.emit_after_review("2026-01-02", review, None)
        assert events.count("a:metrics") == 1
        assert events.count("b:metrics") == 1
        assert events.count("a:review") == 1
        assert events.count("b:review") == 1

    def test_callback_error_does_not_raise(self):
        from duanxian.hooks import HookPack, HookRunner, HookRegistry, LoadedPlugin

        lp = LoadedPlugin(
            id="x",
            path="/x",
            pack=HookPack(
                name="t",
                version="1.0.0",
                schema_bundle="t/1",
                on_metrics_snapshot=lambda c, e: (_ for _ in ()).throw(RuntimeError("boom")),
            ),
        )
        runner = HookRunner([lp], HookRegistry())
        runner.emit_metrics("2026-01-02", {"emotion_metrics": {}, "market_facts": {}}, scope="review")


@pytest.mark.unit
class TestPluginCli:
    def test_cli_register_and_list(self, plugin_home, capsys):
        from duanxian import plugin_cli

        p = plugin_home / "bridge.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        assert plugin_cli.main(["register", str(p)]) == 0
        assert plugin_cli.main(["list"]) == 0
        out = capsys.readouterr().out
        assert "test-hooks" in out
