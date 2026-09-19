"""账户风控闸：评估口径与持仓快照覆盖。"""

from __future__ import annotations

import os

import pytest

from duanxian import risk_guard as rg
from duanxian import risk_guard_config as rgc
from duanxian import trade_store as ts


@pytest.fixture()
def account_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "_ACCOUNT_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "_ACCOUNT_FILE", os.path.join(str(tmp_path), "trade_account.json"))
    monkeypatch.setattr(rgc, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(rgc, "_CONFIG_PATH", os.path.join(str(tmp_path), "risk_guard.json"))
    monkeypatch.setattr(rgc, "_CACHE", None)
    return tmp_path


def _cfg(**overrides):
    c = rgc.resolved()
    c.update(overrides)
    return c


class TestHoldingLossRatio:
    def test_prefers_pnl_pct_points(self):
        assert rg.holding_loss_ratio({"pnl_pct": -5.0, "pnl": -1, "cost": 10, "shares": 100}) == pytest.approx(-0.05)

    def test_falls_back_to_pnl_over_cost(self):
        assert rg.holding_loss_ratio({"pnl": -60, "cost": 10, "shares": 100}) == pytest.approx(-0.06)

    def test_missing_returns_none(self):
        assert rg.holding_loss_ratio({"code": "000001"}) is None


class TestEvaluate:
    def test_single_holding_hard_lists_soft_too(self, account_home):
        out = rg.evaluate(
            "2026-09-18",
            account={"equity": 100000, "snapshots": {}, "holdings_snapshots": {}},
            holdings=[{"code": "000001", "pnl_pct": -7.0, "pnl": -700, "cost": 10, "shares": 100}],
            thresholds=_cfg(),
        )
        levels = {(h["gate"], h["level"]) for h in out["hits"]}
        assert ("single_holding_loss", "soft") in levels
        assert ("single_holding_loss", "hard") in levels
        assert out["global_no_buy"] is True
        assert out["global_no_buy_meta"]["source"] == "risk_guard"
        assert out["global_no_buy_meta"]["level"] == 2

    def test_book_loss_skips_without_snapshot(self, account_home):
        out = rg.evaluate(
            "2026-09-18",
            account={"equity": 100000, "snapshots": {}, "holdings_snapshots": {}},
            holdings=[],
            thresholds=_cfg(),
        )
        assert out["book_loss_skipped"] is True
        assert not any(h["gate"] == "book_loss" for h in out["hits"])

    def test_book_loss_uses_daily_pnl_pct(self, account_home):
        out = rg.evaluate(
            "2026-09-18",
            account={
                "equity": 100000,
                "snapshots": {"2026-09-18": {"equity": 100000, "daily_pnl_pct": -4.2}},
                "holdings_snapshots": {},
            },
            holdings=[],
            thresholds=_cfg(),
        )
        assert out["book_loss_skipped"] is False
        assert any(h["gate"] == "book_loss" and h["level"] == "hard" for h in out["hits"])

    def test_losing_days_missing_snapshot_breaks_streak(self, account_home, monkeypatch):
        monkeypatch.setattr(
            "duanxian.trade_calendar.prev_trade_date",
            lambda d: {"2026-09-18": "2026-09-17", "2026-09-17": "2026-09-16"}.get(d),
        )
        out = rg.evaluate(
            "2026-09-18",
            account={
                "equity": 100000,
                "snapshots": {
                    "2026-09-18": {"equity": 100000, "daily_pnl": -1},
                    # 17 缺快照，打断，即使 16 也亏
                    "2026-09-16": {"equity": 100000, "daily_pnl": -1},
                },
                "holdings_snapshots": {},
            },
            holdings=[],
            thresholds=_cfg(losing_days_soft=2, losing_days_hard=5),
        )
        assert out["losing_day_streak"] == 1
        assert not any(h["gate"] == "losing_days" for h in out["hits"])

    def test_union_uses_last_three_snapshots_overwrite_semantics(self, account_home):
        hsnaps = {
            "2026-09-16": {"holdings": [{"code": "000001", "pnl": -1, "cost": 10, "shares": 1}]},
            "2026-09-17": {"holdings": [{"code": "000002", "pnl": -1, "cost": 10, "shares": 1}]},
            "2026-09-18": {"holdings": [
                {"code": "000003", "pnl": -1, "cost": 10, "shares": 1},
                {"code": "000004", "pnl": -1, "cost": 10, "shares": 1},
                {"code": "000005", "pnl": -1, "cost": 10, "shares": 1},
            ]},
        }
        out = rg.evaluate(
            "2026-09-18",
            account={"equity": 100000, "snapshots": {}, "holdings_snapshots": hsnaps},
            holdings=[{"code": "000003", "pnl": -1, "cost": 10, "shares": 1}],
            thresholds=_cfg(),
        )
        assert set(out["union_codes"]) == {"000001", "000002", "000003", "000004", "000005"}
        hard = next(h for h in out["hits"] if h["gate"] == "losing_holdings_union" and h["level"] == "hard")
        assert out["global_no_buy_meta"]["liquidate"] is True
        assert "000003" in out["global_no_buy_meta"]["codes"]

    def test_max_dd_hard(self, account_home):
        out = rg.evaluate(
            "2026-09-18",
            account={
                "equity": 88000,
                "snapshots": {
                    "2026-09-10": {"equity": 100000},
                    "2026-09-18": {"equity": 88000},
                },
                "holdings_snapshots": {},
            },
            holdings=[],
            thresholds=_cfg(),
        )
        assert any(h["gate"] == "max_dd" and h["level"] == "hard" for h in out["hits"])
        assert out["global_no_buy"] is True

    def test_no_hard_clears_signal(self, account_home):
        out = rg.evaluate(
            "2026-09-18",
            account={"equity": 100000, "snapshots": {}, "holdings_snapshots": {}},
            holdings=[{"code": "000001", "pnl_pct": 1.0, "pnl": 10, "cost": 10, "shares": 10}],
            thresholds=_cfg(),
        )
        assert out["global_no_buy"] is False
        assert out["global_no_buy_reason"] is None
        assert out["global_no_buy_meta"]["level"] == 0


class TestHoldingsSnapshotOverwrite:
    def test_same_day_replace_not_union(self, account_home):
        ts.set_holdings_snapshot("2026-09-18", [{"code": "000001", "pnl": -1, "cost": 1, "shares": 1}])
        ts.set_holdings_snapshot("2026-09-18", [{"code": "000002", "pnl": -1, "cost": 1, "shares": 1}])
        snap = ts.load_account()["holdings_snapshots"]["2026-09-18"]
        codes = [h["code"] for h in snap["holdings"]]
        assert codes == ["000002"]


class TestConfigPairs:
    def test_soft_greater_than_hard_rejected(self, account_home):
        with pytest.raises(rgc.RiskGuardConfigError, match="软阈值"):
            rgc.save_values({"book_loss_soft": 0.05, "book_loss_hard": 0.02})

    def test_export_pairs_soft_hard_on_same_row(self, account_home):
        cfg = rgc.export_config()
        rows = [r for g in cfg["groups"] for r in g["rows"]]
        assert [r["id"] for r in rows] == [
            "single_holding_loss", "book_loss", "losing_days", "losing_holdings_union", "max_dd",
        ]
        holding = next(r for r in rows if r["id"] == "single_holding_loss")
        assert holding["soft"]["key"] == "single_holding_loss_soft"
        assert holding["hard"]["key"] == "single_holding_loss_hard"
        assert holding["soft"]["value"] == pytest.approx(0.04)
        assert holding["hard"]["value"] == pytest.approx(0.06)
