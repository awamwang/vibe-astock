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
class TestMarketSeriesEnsure:
    def test_needs_refresh_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(ms, "_MARGIN_PATH", str(tmp_path / "margin_sse.json"))
        monkeypatch.setattr(ms, "_INDEX_PATH", str(tmp_path / "sh000001.json"))
        monkeypatch.setattr(ms, "_target_trade_date", lambda: "2026-08-21")
        assert ms.needs_refresh() == "两融缓存为空"

    def test_ensure_fresh_skips_when_current(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        margin_path = tmp_path / "margin_sse.json"
        index_path = tmp_path / "sh000001.json"
        monkeypatch.setattr(ms, "_MARGIN_PATH", str(margin_path))
        monkeypatch.setattr(ms, "_INDEX_PATH", str(index_path))
        monkeypatch.setattr(ms, "_target_trade_date", lambda: "2026-08-21")
        ms._save_json(str(margin_path), [{"date": "2026-08-21", "margin_balance": 1.0, "margin_chg": 0.0}])
        ms._save_json(str(index_path), [{"date": "2026-08-21", "close": 1.0, "pct": 0.0}])
        out = ms.ensure_fresh()
        assert out["skipped"] is True
        assert out["ok"] is True

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
        assert out["mode"] == "full"
        assert ms.index_pct_for("2026-08-21") == pytest.approx(1.0)

    def test_amount_metrics_ma20(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(ms, "_AMOUNT_PATH", str(tmp_path / "market_amount.json"))
        rows = []
        for i in range(20):
            rows.append({"date": f"2026-08-{i + 1:02d}", "amount_yi": 100.0 + i})
        rows.append({"date": "2026-08-21", "amount_yi": 150.0})
        ms._save_json(str(tmp_path / "market_amount.json"), rows)
        m = ms.amount_metrics_for("2026-08-21")
        assert m is not None
        assert m["amount_yi"] == 150.0
        assert m["ma20_yi"] == pytest.approx(109.5)
        assert m["amount_vs_ma20"] == pytest.approx(round(150.0 / 109.5, 4))

    def test_parse_exchange_amount(self):
        sse = [{"单日情况": "成交金额", "股票": 1000.0}]
        sz = [{"证券类别": "股票", "成交金额": 2.5e11}]
        assert ms._parse_sse_amount_yi(sse) == 1000.0
        assert ms._parse_szse_amount_yi(sz) == 2500.0

    def test_margin_incremental_merge(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "_CACHE_DIR", str(tmp_path))
        margin_path = tmp_path / "margin_sse.json"
        monkeypatch.setattr(ms, "_MARGIN_PATH", str(margin_path))
        monkeypatch.setattr(ms, "_INDEX_PATH", str(tmp_path / "sh000001.json"))
        monkeypatch.setattr(ms.akc, "available", lambda timeout=2.0: False)
        monkeypatch.setattr(ms, "_target_trade_date", lambda: "2026-08-22")
        monkeypatch.setattr(
            "duanxian.trade_calendar.next_trade_date",
            lambda d: "2026-08-21" if d == "2026-08-20" else "2026-08-22",
        )

        ms._save_json(
            str(margin_path),
            [{"date": "2026-08-20", "margin_balance": 100.0, "margin_buy": 1.0, "margin_chg": None}],
        )

        calls: list[dict] = []

        def fake_akshare_margin(**kw):
            calls.append(kw)
            class DF:
                def __len__(self):
                    return len(self._rows)

                def __init__(self):
                    self._rows = [
                        {"信用交易日期": "2026-08-21", "融资余额": 110.0, "融资买入额": 2.0},
                        {"信用交易日期": "2026-08-22", "融资余额": 121.0, "融资买入额": 3.0},
                    ]

                def to_dict(self, orient="records"):
                    return self._rows

            return DF()

        import types
        import sys

        fake = types.ModuleType("akshare")
        fake.stock_margin_sse = fake_akshare_margin
        monkeypatch.setitem(sys.modules, "akshare", fake)

        out = ms.refresh_margin()
        assert out["ok"] is True
        assert out["mode"] == "incremental"
        assert out["days"] == 3
        assert calls and calls[0].get("start_date") == "20260821"
        row = ms.margin_for("2026-08-22")
        assert row is not None
        assert row["margin_chg"] == pytest.approx(10.0)
