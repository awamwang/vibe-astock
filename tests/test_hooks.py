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

    def test_merge_plugin_overrides_manual_same_code(self, tmp_path, monkeypatch):
        import watchlist as wl

        wl_file = tmp_path / "watchlist.json"
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(wl, "WL_FILE", str(wl_file))
        monkeypatch.setattr(wl, "CACHE_DIR", str(tmp_path))

        wl.sync_codes_from_ui(["600000"])
        source = "插件：vibe-ths-linker（同花顺）"
        wl.merge_plugin_codes(["600000"], source)
        items = {it["code"]: it for it in wl.get_watchlist()["items"]}
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

    def test_report_current_stock(self):
        from duanxian import current_stock as cs
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug0001")
        res = reg.report_current_stock({
            "code": "600000",
            "source": "push",
            "ths_dir": "C:\\同花顺",
            "symbol": "600000.SH",
        })
        assert res.ok
        assert res.kind == "current_stock"
        assert res.detail == "600000"
        data = cs.to_dict()
        assert data is not None
        assert data["code"] == "600000"
        assert data["plugin_id"] == "plug0001"
        assert data["source"] == "push"
        assert data["ths_dir"] == "C:\\同花顺"

        res2 = reg.report_current_stock({"code": "600000", "source": "push"})
        assert res2.ok
        assert res2.detail == "unchanged"

        res3 = reg.report_current_stock({"code": "000001", "source": "push", "prev": "600000"})
        assert res3.detail == "000001"
        data3 = cs.to_dict()
        assert data3["prev"] == "600000"

    def test_current_stock_subscribe_notify(self):
        import threading

        from duanxian import current_stock as cs
        from duanxian.hooks import HookRegistry

        cs._current = None  # noqa: SLF001
        sub = cs.subscribe()
        reg = HookRegistry()
        reg.bind_plugin("plug0002")
        err: list[Exception] = []

        def _report() -> None:
            try:
                reg.report_current_stock({"code": "600519", "source": "push"})
            except Exception as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=_report)
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "report_current_stock 死锁"
        assert not err
        msg = sub.get(timeout=1.0)
        assert msg is not None
        assert msg["code"] == "600519"
        cs.unsubscribe(sub)

    def test_report_current_stock_requires_bind(self):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        with pytest.raises(RuntimeError, match="bind_plugin"):
            reg.report_current_stock({"code": "600000"})

    def test_report_current_stock_rejects_bad_code(self):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug0001")
        with pytest.raises(ValueError, match="6 位数字"):
            reg.report_current_stock({"code": "bad"})


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

        from duanxian import hooks
        from duanxian import plugin_store as ps
        from duanxian.hooks import (
            _module_name,
            apply_plugin_disable,
            apply_plugin_enable,
        )

        p = plugin_home / "lifecycle.py"
        p.write_text(self._LIFECYCLE_SRC, encoding="utf-8")
        rec = ps.register(str(p))

        assert apply_plugin_enable(rec.id) is not None
        mod_obj = sys.modules[_module_name(rec.id)]
        assert mod_obj._STATE["active"] is True
        assert rec.id in {lp.id for lp in hooks.PLUGINS}
        assert rec.id in {lp.id for lp in hooks.RUNNER.plugins}

        assert apply_plugin_disable(rec.id) is True
        assert mod_obj._STATE["active"] is False
        assert rec.id not in {lp.id for lp in hooks.PLUGINS}

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

    def test_enable_runtime_error_shows_friendly_message(self, plugin_home):
        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian.hooks import apply_plugin_enable, PLUGINS

        src = '''
from duanxian.hooks import HookPack, HookRegistry

def on_enable(reg: HookRegistry) -> None:
    raise RuntimeError("无法连接 ths-linker：请先启动服务")

PACK = HookPack(
    name="fail-enable",
    version="1",
    schema_bundle="t/1",
    on_enable=on_enable,
)
'''
        p = plugin_home / "fail_enable.py"
        p.write_text(src, encoding="utf-8")
        rec = ps.register(str(p))
        lp = apply_plugin_enable(rec.id)
        assert lp is not None
        assert rec.id in {x.id for x in PLUGINS}
        st = pstat.get_status(rec.id)
        assert st is not None
        assert st.level == "error"
        assert st.message == "无法连接 ths-linker：请先启动服务"
        assert st.detail is None

    def test_apply_plugin_restart_reloads_module(self, plugin_home):
        import sys

        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian.hooks import (
            _module_name,
            apply_plugin_enable,
            apply_plugin_restart,
            PLUGINS,
        )

        p = plugin_home / "restart_me.py"
        p.write_text(self._LIFECYCLE_SRC, encoding="utf-8")
        rec = ps.register(str(p))
        apply_plugin_enable(rec.id)
        mod1 = sys.modules[_module_name(rec.id)]
        assert mod1._STATE["active"] is True

        lp = apply_plugin_restart(rec.id)
        assert lp is not None
        assert rec.id in {x.id for x in PLUGINS}
        mod2 = sys.modules[_module_name(rec.id)]
        assert mod2._STATE["active"] is True
        assert mod1 is not mod2
        st = pstat.get_status(rec.id)
        assert st is not None
        assert st.level == "ok"
        assert st.message == "已加载"

    def test_enable_recovers_from_loading_placeholder(self, plugin_home):
        """启动占位「加载中…」在 on_enable 成功后必须恢复，不能一直停在加载态。"""
        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian.hooks import apply_plugin_enable

        p = plugin_home / "loading_ok.py"
        p.write_text(self._LIFECYCLE_SRC, encoding="utf-8")
        rec = ps.register(str(p))
        pstat.set_status(rec.id, "info", pstat.MSG_LOADING)
        apply_plugin_enable(rec.id)
        st = pstat.get_status(rec.id)
        assert st is not None
        assert st.level == "ok"
        assert st.message == "已加载"
        assert not pstat.is_engine_transient(st)

    def test_enable_keeps_plugin_reported_ok(self, plugin_home):
        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian.hooks import apply_plugin_enable

        src = '''
from duanxian.hooks import HookPack, HookRegistry

def on_enable(reg: HookRegistry) -> None:
    reg.report_status("info", "加载中…")
    reg.report_status("ok", "已连接 ths-linker", "pid=1")

PACK = HookPack(
    name="report-ok",
    version="1",
    schema_bundle="t/1",
    on_enable=on_enable,
)
'''
        p = plugin_home / "report_ok.py"
        p.write_text(src, encoding="utf-8")
        rec = ps.register(str(p))
        apply_plugin_enable(rec.id)
        st = pstat.get_status(rec.id)
        assert st is not None
        assert st.level == "ok"
        assert st.message == "已连接 ths-linker"


@pytest.mark.unit
class TestPluginSupervisor:
    @pytest.fixture(autouse=True)
    def _isolate_supervisor(self, monkeypatch):
        from duanxian import plugin_supervisor as psup

        # 关闭守护轮询，仅手动调用 _tick，避免与用例竞态
        monkeypatch.setenv("VIBE_PLUGIN_SUPERVISOR", "0")
        psup.reset_state_for_tests()
        yield
        psup.reset_state_for_tests()

    def test_backoff_delay_grows_exponentially(self):
        from duanxian.plugin_supervisor import _backoff_delay

        assert _backoff_delay(0, 5.0, 300.0) == 5.0
        assert _backoff_delay(1, 5.0, 300.0) == 10.0
        assert _backoff_delay(2, 5.0, 300.0) == 20.0
        assert _backoff_delay(10, 5.0, 300.0) == 300.0

    def test_tick_restarts_error_plugin_after_backoff(self, plugin_home, monkeypatch):
        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian import plugin_supervisor as psup
        from duanxian.hooks import apply_plugin_enable, PLUGINS

        monkeypatch.setenv("VIBE_PLUGIN_RETRY_BASE_SEC", "1")
        monkeypatch.setenv("VIBE_PLUGIN_RETRY_MAX_SEC", "8")

        counter = plugin_home / "flaky_count.txt"
        counter.write_text("0", encoding="utf-8")
        counter_s = str(counter).replace("\\", "/")
        src = f'''
from pathlib import Path
from duanxian.hooks import HookPack, HookRegistry

_COUNTER = Path("{counter_s}")

def on_enable(reg: HookRegistry) -> None:
    n = int(_COUNTER.read_text(encoding="utf-8") or "0") + 1
    _COUNTER.write_text(str(n), encoding="utf-8")
    if n <= 1:
        raise RuntimeError("暂时不可用")
    reg.report_status("ok", "已恢复")

def on_disable() -> None:
    pass

PACK = HookPack(
    name="flaky",
    version="1",
    schema_bundle="t/1",
    on_enable=on_enable,
    on_disable=on_disable,
)
'''
        p = plugin_home / "flaky.py"
        p.write_text(src, encoding="utf-8")
        rec = ps.register(str(p))
        apply_plugin_enable(rec.id)
        st = pstat.get_status(rec.id)
        assert st is not None and st.level == "error"
        assert counter.read_text(encoding="utf-8") == "1"

        # 首次发现：只登记，等 base 秒后再重启
        t0 = 1000.0
        psup._tick(now=t0)
        with psup._lock:
            state = psup._states[rec.id]
            assert state.attempt == 0
            assert state.next_at == t0 + 1.0

        # 到期：执行重启，第二次 on_enable 成功
        psup._tick(now=t0 + 1.0)
        assert rec.id in {x.id for x in PLUGINS}
        assert counter.read_text(encoding="utf-8") == "2"
        st2 = pstat.get_status(rec.id)
        assert st2 is not None
        assert st2.level == "ok"
        assert "已恢复" in st2.message
        with psup._lock:
            assert rec.id not in psup._states

    def test_tick_increases_backoff_when_still_error(self, plugin_home, monkeypatch):
        import time

        from duanxian import plugin_status as pstat
        from duanxian import plugin_store as ps
        from duanxian import plugin_supervisor as psup
        from duanxian.hooks import apply_plugin_enable

        monkeypatch.setenv("VIBE_PLUGIN_RETRY_BASE_SEC", "2")
        monkeypatch.setenv("VIBE_PLUGIN_RETRY_MAX_SEC", "100")

        src = '''
from duanxian.hooks import HookPack, HookRegistry

def on_enable(reg: HookRegistry) -> None:
    raise RuntimeError("持续失败")

PACK = HookPack(
    name="always-fail",
    version="1",
    schema_bundle="t/1",
    on_enable=on_enable,
)
'''
        p = plugin_home / "always_fail.py"
        p.write_text(src, encoding="utf-8")
        rec = ps.register(str(p))
        apply_plugin_enable(rec.id)

        t0 = 2000.0
        psup._tick(now=t0)
        before = time.monotonic()
        psup._tick(now=t0 + 2.0)
        with psup._lock:
            state = psup._states[rec.id]
            assert state.attempt == 1
            # 重启后下次间隔 2 * 2^1 = 4s（相对真实 monotonic）
            assert state.next_at >= before + 4.0 - 0.5
            assert state.next_at <= time.monotonic() + 4.0 + 0.5
        st = pstat.get_status(rec.id)
        assert st is not None
        assert st.level == "error"
        assert "后自动重启" in st.message

    @pytest.fixture(autouse=True)
    def _clean_sources(self):
        from duanxian import message_sources as ms

        ms.clear_all()
        yield
        ms.clear_all()

    @pytest.fixture
    def push_store(self, tmp_path, monkeypatch):
        from duanxian.hooks import _ensure_vr_path

        _ensure_vr_path()
        import message.store as msg_store

        path = str(tmp_path / "messages.db")
        monkeypatch.setattr(msg_store, "DB_PATH", path)
        msg_store.init_db(path)
        return msg_store, path

    def test_register_and_list_sources(self, push_store):
        msg_store, path = push_store
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug_msg1")
        res = reg.register_message_source("my_feed", "我的快讯")
        assert res.ok
        assert res.detail == "my_feed"

        sources = msg_store.list_sources(path=path)
        plugin_srcs = [s for s in sources if s.adapter_type == "plugin"]
        assert len(plugin_srcs) == 1
        assert plugin_srcs[0].id == "my_feed"
        assert plugin_srcs[0].label == "我的快讯"
        assert plugin_srcs[0].enabled is True

    def test_push_raw_only_and_auto_analyze(self, push_store):
        msg_store, path = push_store
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug_msg1")
        reg.register_message_source("my_feed", "我的快讯")

        res = reg.push_messages({
            "source_id": "my_feed",
            "messages": [
                {"content": "仅 raw 消息", "external_ref": "e1", "title": "标题一"},
            ],
        })
        assert res.ok
        assert "inserted=1" in res.detail
        assert "analyzed=0" in res.detail
        raws, total = msg_store.list_raw(msg_store.ListQuery(source="my_feed"), path=path)
        assert total == 1
        assert raws[0].content == "仅 raw 消息"
        analyzed, an_total = msg_store.list_analyzed(
            msg_store.ListQuery(source="my_feed"), path=path
        )
        assert an_total == 0

        res2 = reg.push_messages({
            "source_id": "my_feed",
            "auto_analyze": True,
            "messages": [
                {
                    "content": "带分析消息",
                    "external_ref": "e2",
                    "title": "标题二",
                    "summary": "摘要",
                    "impact_level": "high",
                    "targets": [{"kind": "stock", "code": "600000", "name": "浦发银行"}],
                },
            ],
        })
        assert "inserted=1" in res2.detail
        assert "analyzed=1" in res2.detail
        analyzed, an_total = msg_store.list_analyzed(
            msg_store.ListQuery(source="my_feed"), path=path
        )
        assert an_total == 1
        assert analyzed[0].summary == "摘要"
        assert analyzed[0].impact_level == "high"
        assert any(t.code == "600000" for t in analyzed[0].targets)

    def test_external_ref_idempotent(self, push_store):
        msg_store, path = push_store
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug_msg1")
        reg.register_message_source("my_feed")
        payload = {
            "source_id": "my_feed",
            "messages": [{"content": "同一条", "external_ref": "dup-1"}],
        }
        assert "inserted=1" in reg.push_messages(payload).detail
        assert "inserted=0" in reg.push_messages(payload).detail
        _, total = msg_store.list_raw(msg_store.ListQuery(source="my_feed"), path=path)
        assert total == 1

    def test_rejects_unregistered_and_foreign_and_unbound(self, push_store):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        with pytest.raises(RuntimeError, match="bind_plugin"):
            reg.register_message_source("my_feed")

        reg.bind_plugin("plug_msg1")
        reg.register_message_source("my_feed")

        with pytest.raises(ValueError, match="未注册"):
            reg.push_messages({
                "source_id": "other_feed",
                "messages": [{"content": "x"}],
            })

        reg2 = HookRegistry()
        reg2.bind_plugin("plug_msg2")
        with pytest.raises(ValueError, match="不属于"):
            reg2.push_messages({
                "source_id": "my_feed",
                "messages": [{"content": "x"}],
            })

    def test_rejects_reserved_source_id(self):
        from duanxian.hooks import HookRegistry

        reg = HookRegistry()
        reg.bind_plugin("plug_msg1")
        with pytest.raises(ValueError, match="保留"):
            reg.register_message_source("cls_telegraph", "财联社")

    def test_deactivate_unregisters_source(self, push_store):
        msg_store, path = push_store
        from duanxian.hooks import HookPack, HookRegistry, LoadedPlugin, _deactivate_plugin

        reg = HookRegistry()
        reg.bind_plugin("plug_msg1")
        reg.register_message_source("my_feed", "我的快讯")
        assert any(s.id == "my_feed" for s in msg_store.list_sources(path=path))

        lp = LoadedPlugin(
            id="plug_msg1",
            path="/tmp/x.py",
            pack=HookPack(name="t", version="1", schema_bundle="t/1"),
        )
        _deactivate_plugin(lp)
        assert not any(
            s.id == "my_feed" and s.adapter_type == "plugin"
            for s in msg_store.list_sources(path=path)
        )
        with pytest.raises(ValueError, match="未注册"):
            reg.push_messages({
                "source_id": "my_feed",
                "messages": [{"content": "停用后"}],
            })


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
