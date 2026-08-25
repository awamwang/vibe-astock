"""AKTools 托管与市场序列缓存。"""

from __future__ import annotations

import pytest

from duanxian import aktools_service as aks
from duanxian import market_series as ms


@pytest.mark.unit
class TestAktoolsService:
    def test_managed_flag(self, monkeypatch):
        monkeypatch.delenv("AKTOOLS_MANAGED", raising=False)
        assert aks.managed_enabled() is True
        monkeypatch.setenv("AKTOOLS_MANAGED", "0")
        assert aks.managed_enabled() is False

    def test_ensure_skips_when_disabled(self, monkeypatch):
        monkeypatch.setenv("AKTOOLS_MANAGED", "0")
        monkeypatch.setattr(aks.akc, "available", lambda timeout=1.0: False)
        out = aks.ensure_started(wait_s=0.5)
        assert out["ok"] is False
        assert "AKTOOLS_MANAGED=0" in (out.get("error") or "")


@pytest.mark.unit
class TestMarketSeriesParse:
    def test_margin_chg_from_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(ms, "_MARGIN_PATH", str(tmp_path / "margin_sse.json"))
        monkeypatch.setattr(ms, "_INDEX_PATH", str(tmp_path / "sh000001.json"))
        monkeypatch.setattr(ms.akc, "available", lambda timeout=2.0: False)

        def fake_akshare_margin(**_kw):
            class DF:
                def __len__(self):
                    return 2

                def to_dict(self, orient="records"):
                    return [
                        {"信用交易日期": "2026-08-20", "融资余额": 100.0, "融资买入额": 1.0},
                        {"信用交易日期": "2026-08-21", "融资余额": 110.0, "融资买入额": 2.0},
                    ]

            return DF()

        import types
        import sys

        fake = types.ModuleType("akshare")
        fake.stock_margin_sse = fake_akshare_margin
        monkeypatch.setitem(sys.modules, "akshare", fake)

        out = ms.refresh_margin()
        assert out["ok"] is True
        assert out["days"] == 2
        row = ms.margin_for("2026-08-21")
        assert row is not None
        assert row["margin_chg"] == pytest.approx(10.0)

    def test_index_pct_from_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(ms, "_MARGIN_PATH", str(tmp_path / "margin_sse.json"))
        monkeypatch.setattr(ms, "_INDEX_PATH", str(tmp_path / "sh000001.json"))
        monkeypatch.setattr(ms.akc, "available", lambda timeout=2.0: False)

        def fake_index(**_kw):
            class DF:
                def to_dict(self, orient="records"):
                    return [
                        {"date": "2026-08-20", "close": 100.0},
                        {"date": "2026-08-21", "close": 101.0},
                    ]

                def __len__(self):
                    return 2

            return DF()

        import types
        import sys

        fake = types.ModuleType("akshare")
        fake.stock_zh_index_daily = fake_index
        monkeypatch.setitem(sys.modules, "akshare", fake)

        out = ms.refresh_index()
        assert out["ok"] is True
        assert ms.index_pct_for("2026-08-21") == pytest.approx(1.0)
