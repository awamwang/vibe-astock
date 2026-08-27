"""股票列表获取器单元测试（不打真实网络）。"""

from __future__ import annotations

import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

_VR_DIR = str(Path(__file__).resolve().parents[1] / "vr")
if _VR_DIR not in sys.path:
    sys.path.insert(0, _VR_DIR)

import stock_universe as su


@pytest.fixture(autouse=True)
def _reset_universe(monkeypatch, tmp_path):
    monkeypatch.setattr(su, "_by_code", {})
    monkeypatch.setattr(su, "_name_to_code", {})
    monkeypatch.setattr(su, "_loaded", False)
    monkeypatch.setattr(su, "_meta", su.LoadMeta(ok=False))
    monkeypatch.setattr(su, "_cache_updated_at", None)
    monkeypatch.setattr(su, "_REFRESH_RUNNING", False)
    monkeypatch.setattr(su, "_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("STOCK_LIST_SOURCES", raising=False)


@pytest.mark.unit
class TestInfer:
    def test_market(self):
        assert su.infer_market("600000") == "SH"
        assert su.infer_market("000001") == "SZ"
        assert su.infer_market("830001") == "BJ"
        assert su.infer_market("688001") == "SH"

    def test_st_name(self):
        assert su._is_st("*ST美丽")
        assert su._is_st("ST海王")
        assert not su._is_st("贵州茅台")

    def test_build_types_board_and_st(self):
        today = date(2026, 8, 27)
        types = su.build_types("688001", "*ST测试", board_hint="科创板", today=today)
        assert "科创板" in types
        assert "ST" in types

    def test_build_types_new_and_subnew(self):
        today = date(2026, 8, 27)
        new = today - timedelta(days=10)
        sub = today - timedelta(days=120)
        assert "新股" in su.build_types("300001", "某新", list_date=new, today=today)
        assert "次新股" in su.build_types("300002", "某次", list_date=sub, today=today)


@pytest.mark.unit
class TestConfig:
    def test_default_sources(self):
        assert su.configured_sources() == ("eastmoney", "akshare")

    def test_read_source_order(self):
        assert su.read_source_order() == ("cache", "eastmoney", "akshare")

    def test_env_sources(self, monkeypatch):
        monkeypatch.setenv("STOCK_LIST_SOURCES", "akshare,eastmoney,invalid")
        assert su.configured_sources() == ("akshare", "eastmoney")
        assert su.read_source_order() == ("cache", "akshare", "eastmoney")


@pytest.mark.unit
class TestLoad:
    def _sample_items(self) -> list[su.StockItem]:
        return [
            su.StockItem(code="600000", name="浦发银行", market="SH", types=("主板",)),
            su.StockItem(code="000001", name="平安银行", market="SZ", types=("主板",)),
        ]

    def test_network_first_source_ok(self, monkeypatch):
        items = self._sample_items()

        def _em(**_k):
            return items

        monkeypatch.setitem(su._FETCHERS, "eastmoney", _em)
        meta = su.load_stock_universe(force=True)
        assert meta.ok is True
        assert meta.source == "eastmoney"
        assert meta.count == 2
        assert su.get_stock_by_code("600000").name == "浦发银行"
        assert Path(su._cache_path()).is_file()

    def test_network_fallback_second_source(self, monkeypatch):
        items = self._sample_items()

        def _em_fail(**_k):
            raise RuntimeError("network")

        def _ak(**_k):
            return items

        monkeypatch.setitem(su._FETCHERS, "eastmoney", _em_fail)
        monkeypatch.setitem(su._FETCHERS, "akshare", _ak)
        meta = su.load_stock_universe(force=True)
        assert meta.ok is True
        assert meta.source == "akshare"

    def test_network_skips_akshare_when_eastmoney_ok(self, monkeypatch):
        items = self._sample_items()
        calls: list[str] = []

        def _em(**_k):
            calls.append("eastmoney")
            return items

        def _ak(**_k):
            calls.append("akshare")
            return items

        monkeypatch.setitem(su._FETCHERS, "eastmoney", _em)
        monkeypatch.setitem(su._FETCHERS, "akshare", _ak)
        meta = su.load_stock_universe(force=True)
        assert meta.ok is True
        assert meta.source == "eastmoney"
        assert calls == ["eastmoney"]

    def test_all_sources_fail(self, monkeypatch):
        def _fail(**_k):
            raise RuntimeError("down")

        monkeypatch.setitem(su._FETCHERS, "eastmoney", _fail)
        monkeypatch.setitem(su._FETCHERS, "akshare", _fail)
        meta = su.load_stock_universe(force=True)
        assert meta.ok is False
        assert su.get_stock_list() == []

    def test_load_without_cache_fails_softly(self):
        meta = su.load_stock_universe()
        assert meta.ok is False
        assert "本地无股票列表缓存" in (meta.error or "")

    def test_load_from_cache(self, monkeypatch):
        items = self._sample_items()
        monkeypatch.setitem(su._FETCHERS, "eastmoney", lambda **_k: items)
        su.load_stock_universe(force=True)
        su._loaded = False
        su._meta = su.LoadMeta(ok=False)
        meta = su.load_from_cache()
        assert meta.ok is True
        assert meta.source == "cache"
        assert meta.from_cache is True
        assert meta.count == 2

    def test_resolve_code_by_name(self, monkeypatch):
        monkeypatch.setitem(su._FETCHERS, "eastmoney", lambda **_k: self._sample_items())
        su.load_stock_universe(force=True)
        assert su.resolve_code_by_name("浦发银行") == "600000"
        assert su.resolve_code_by_name("浦发银行（龙虎榜）") == "600000"
        assert su.get_name_to_code()["平安银行"] == "000001"


@pytest.mark.unit
class TestRefresh:
    def test_schedule_refresh_runs_in_background(self, monkeypatch):
        started = threading.Event()

        def _slow(**_k):
            started.set()
            time.sleep(0.05)
            return [su.StockItem(code="600000", name="浦发银行", market="SH", types=("主板",))]

        monkeypatch.setitem(su._FETCHERS, "eastmoney", _slow)
        su.schedule_refresh()
        assert started.wait(1.0)
        deadline = time.time() + 2.0
        while time.time() < deadline and not su.is_loaded():
            time.sleep(0.02)
        assert su.is_loaded() is True
        assert su.is_refreshing() is False


@pytest.mark.unit
class TestReflectionIntegration:
    def test_name_code_map_uses_universe(self, monkeypatch):
        monkeypatch.setitem(
            su._FETCHERS,
            "eastmoney",
            lambda **_k: [
                su.StockItem(code="600519", name="贵州茅台", market="SH", types=("主板",)),
            ],
        )
        from duanxian import reflection as rf

        su.load_stock_universe(force=True)
        m = rf._name_code_map()
        assert m.get("贵州茅台") == "600519"
