"""股票处理器单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

VR = Path(__file__).resolve().parents[1] / "vr"
if str(VR) not in sys.path:
    sys.path.insert(0, str(VR))

import stock_processor as sp
import stock_universe as su


@pytest.fixture(autouse=True)
def _reset_universe(monkeypatch):
    monkeypatch.setattr(su, "_by_code", {})
    monkeypatch.setattr(su, "_name_to_code", {})
    monkeypatch.setattr(su, "_loaded", False)
    monkeypatch.setattr(su, "_meta", su.LoadMeta(ok=False))
    items = [
        su.StockItem(code="600000", name="浦发银行", market="SH", types=("主板",)),
        su.StockItem(code="000001", name="平安银行", market="SZ", types=("主板",)),
    ]
    su._apply_items(items, "cache", tried=("cache",), updated_at="2026-08-27 12:00:00", from_cache=True)


@pytest.mark.unit
class TestStockProcessor:
    def test_make_key_prefers_code(self):
        assert sp.make_key(code="1", name="平安银行") == "c:000001"
        assert sp.make_key(name="平安银行") == "n:平安银行"

    def test_resolve_by_code(self):
        hit = sp.resolve_one(code="600000")
        assert hit["status"] == "matched"
        assert hit["stock"]["name"] == "浦发银行"

    def test_resolve_by_name(self):
        hit = sp.resolve_one(name="平安银行")
        assert hit["status"] == "matched"
        assert hit["stock"]["code"] == "000001"

    def test_resolve_name_with_paren(self):
        hit = sp.resolve_one(name="浦发银行（测试）")
        assert hit["status"] == "matched"
        assert hit["stock"]["code"] == "600000"

    def test_resolve_unmatched(self):
        hit = sp.resolve_one(name="不存在板块名")
        assert hit["status"] == "unmatched"
        assert hit["stock"] is None

    def test_export_resolve_by_key(self):
        data = sp.export_resolve([
            {"code": "600000", "name": "浦发银行"},
            {"name": "半导体"},
        ])
        assert "c:600000" in data["by_key"]
        assert data["by_key"]["c:600000"]["status"] == "matched"
        assert data["by_key"]["n:半导体"]["status"] == "unmatched"
