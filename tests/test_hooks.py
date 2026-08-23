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

    def test_import_watchlist_replace(self, tmp_path, monkeypatch):
        vr_dir = str(Path(__file__).resolve().parents[1] / "vr")
        if vr_dir not in sys.path:
            sys.path.insert(0, vr_dir)
        import watchlist as wl

        from duanxian.hooks import HookRegistry

        wl_file = tmp_path / "watchlist.json"
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(wl, "WL_FILE", str(wl_file))
        monkeypatch.setattr(wl, "CACHE_DIR", str(tmp_path))

        reg = HookRegistry()
        res = reg.import_watchlist({
            "replace": True,
            "codes": ["600000", "000001", "bad", "600000"],
        })
        assert res.ok
        assert res.kind == "watchlist"
        assert wl.get_codes() == ["600000", "000001"]
        data = wl.get_watchlist()
        assert all(it["source"] == wl.SOURCE_MANUAL for it in data["items"])

    def test_import_watchlist_merge_plugin(self, tmp_path, monkeypatch):
        vr_dir = str(Path(__file__).resolve().parents[1] / "vr")
        if vr_dir not in sys.path:
            sys.path.insert(0, vr_dir)
        import watchlist as wl

        from duanxian.hooks import HookRegistry

        wl_file = tmp_path / "watchlist.json"
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(wl, "WL_FILE", str(wl_file))
        monkeypatch.setattr(wl, "CACHE_DIR", str(tmp_path))

        wl.sync_codes_from_ui(["600519"])
        source = "插件：vibe-ths-linker（同花顺）"
        reg = HookRegistry()
        res = reg.import_watchlist({
            "merge": True,
            "source": source,
            "codes": ["600000", "000001"],
        })
        assert res.ok
        assert wl.get_codes() == ["600000", "000001", "600519"]
        items = {it["code"]: it for it in wl.get_watchlist()["items"]}
        assert items["600519"]["source"] == wl.SOURCE_MANUAL
        assert items["600000"]["source"] == source

    def test_sync_codes_from_ui_remove_keeps_updated_at(self, tmp_path, monkeypatch):
        import watchlist as wl

        wl_file = tmp_path / "watchlist.json"
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(wl, "WL_FILE", str(wl_file))
        monkeypatch.setattr(wl, "CACHE_DIR", str(tmp_path))

        first = wl.sync_codes_from_ui(["600000", "000001"])
        stamp = first["updated_at"]
        second = wl.sync_codes_from_ui(["600000"])
        assert second["updated_at"] == stamp
        items = {it["code"]: it for it in second["items"]}
        assert items["600000"]["source"] == wl.SOURCE_MANUAL

    def test_import_watchlist_rejects_invalid_mode(self):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        with pytest.raises(ValueError, match="replace=true"):
            reg.import_watchlist({"replace": False, "codes": ["600000"]})


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
        from duanxian import plugin_status as ps
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
        st = ps.get_status("x")
        assert st is not None
        assert st.level == "warn"
        assert "钩子回调失败" in st.message


@pytest.mark.unit
class TestPluginStatus:
    def test_report_status_via_registry(self):
        from duanxian import plugin_status as ps
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("abc12345")
        reg.report_status("info", "等待连接", "ws://127.0.0.1")
        st = ps.get_status("abc12345")
        assert st is not None
        assert st.level == "info"
        assert st.message == "等待连接"
        assert st.detail == "ws://127.0.0.1"

    def test_resolve_runtime_status_disabled(self):
        from duanxian import plugin_status as ps

        out = ps.resolve_runtime_status(
            "abc",
            enabled=False,
            file_exists=True,
            loaded=False,
        )
        assert out["level"] == "off"
        assert out["message"] == "已停用"

    def test_load_failure_records_status(self, plugin_home):
        from duanxian import plugin_status as ps
        from duanxian import plugin_store as store
        from duanxian.hooks import load_plugins

        p = plugin_home / "bad.py"
        p.write_text(_PLUGIN_SRC, encoding="utf-8")
        rec = store.register(str(p))
        p.write_text("PACK = 1\n", encoding="utf-8")
        load_plugins()
        st = ps.get_status(rec.id)
        assert st is not None
        assert st.level == "error"
        assert st.message == "加载失败"


@pytest.mark.unit
class TestPluginLifecycle:
    _LIFECYCLE_SRC = '''
from __future__ import annotations
from duanxian.hooks import HookPack, HookRegistry

_STATE = {"active": False}

def on_enable(reg: HookRegistry) -> None:
    _STATE["active"] = True

def on_disable() -> None:
    _STATE["active"] = False

PACK = HookPack(
    name="lifecycle-test",
    version="1.0.0",
    schema_bundle="test/1",
    on_enable=on_enable,
    on_disable=on_disable,
)
'''

    def test_apply_enable_disable(self, plugin_home):
        import sys

        from duanxian import plugin_store as ps
        from duanxian.hooks import (
            _module_name,
            apply_plugin_disable,
            apply_plugin_enable,
            PLUGINS,
            RUNNER,
        )

        p = plugin_home / "lifecycle.py"
        p.write_text(self._LIFECYCLE_SRC, encoding="utf-8")
        rec = ps.register(str(p))

        assert apply_plugin_enable(rec.id) is not None
        mod_obj = sys.modules[_module_name(rec.id)]
        assert mod_obj._STATE["active"] is True
        assert rec.id in {lp.id for lp in PLUGINS}
        assert rec.id in {lp.id for lp in RUNNER.plugins}

        assert apply_plugin_disable(rec.id) is True
        assert mod_obj._STATE["active"] is False
        assert rec.id not in {lp.id for lp in PLUGINS}

    def test_on_register_fallback_for_enable(self, plugin_home):
        from duanxian import plugin_store as ps
        from duanxian.hooks import apply_plugin_disable, apply_plugin_enable, PLUGINS

        src = '''
from duanxian.hooks import HookPack, HookRegistry
def on_register(reg: HookRegistry) -> None:
    pass
PACK = HookPack(name="legacy", version="1", schema_bundle="t/1", on_register=on_register)
'''
        p = plugin_home / "legacy.py"
        p.write_text(src, encoding="utf-8")
        rec = ps.register(str(p))
        lp = apply_plugin_enable(rec.id)
        assert lp is not None
        assert rec.id in {x.id for x in PLUGINS}
        apply_plugin_disable(rec.id)


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


@pytest.mark.unit
class TestPluginStoreUi:
    def test_open_entry_dir(self, plugin_home, monkeypatch):
        from duanxian import plugin_store as ps

        p = plugin_home / "pkg" / "bridge.py"
        p.parent.mkdir(parents=True)
        p.write_text("x = 1\n", encoding="utf-8")
        revealed: list[str] = []
        monkeypatch.setattr(ps, "_reveal_dir", lambda path: revealed.append(str(path)))
        opened = ps.open_entry_dir(str(p))
        assert opened == str(p.parent.resolve())
        assert revealed == [str(p.parent.resolve())]
