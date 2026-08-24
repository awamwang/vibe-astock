"""当日风险姿态：读数组装 + guard 同处，不打分类器细节。"""

from __future__ import annotations

import pytest

from duanxian import risk_stance as rs


def _budget(**kw):
    b = {
        "available": True,
        "phase": "升温扩张",
        "cap_total": 0.60,
        "cap_single": 0.10,
        "expansion_allowed": True,
        "block_new_long_reasons": [],
    }
    b.update(kw)
    return b


@pytest.mark.unit
class TestGatherReadings:
    def test_uses_archive_emotion_half(self, monkeypatch):
        monkeypatch.setattr("duanxian.trade_calendar.prev_trade_date", lambda _d: None)
        monkeypatch.setattr("duanxian.emotion_metrics.day_summary", lambda _d: {
            "limit_up": 40, "highest_consec": 4, "broken_rate": 0.2,
        })
        monkeypatch.setattr(
            "duanxian.settled_archive.emotion_half",
            lambda _d, with_cycle=False: {
                "money_effect": {"available": True, "median": 1.2},
                "promotion": {"available": True, "tiers": {"1进2": {"rate": 0.3}}},
                "ladder_gap": {"available": True, "highest": 4},
            },
        )
        monkeypatch.setattr(
            "duanxian.market_facts.loss_effect",
            lambda *_a, **_k: {"available": True, "deep_loss_5_rate": 0.08, "market_limit_down": 3},
        )
        monkeypatch.setattr(
            "duanxian.breadth.market_breadth",
            lambda _d: {"available": True, "up": 3000, "down": 2000},
        )
        monkeypatch.setattr(rs, "_hist_highest", lambda _d, lookback=5: [3, 4])
        monkeypatch.setattr(rs, "_index_pct_for", lambda _d: 0.4)

        out = rs.gather_readings("2026-08-20")
        assert out["money_ok"] is True
        assert out["money_median"] == 1.2
        assert out["promotion_1to2"] == 0.3
        assert out["highest"] == 4
        assert out["limit_up"] == 40
        assert out["up"] == 3000


@pytest.mark.unit
class TestGuard:
    def test_unavailable_budget_skips_position(self):
        out = rs.guard(
            "2026-08-20",
            budget={"available": False, "block_new_long_reasons": ["缺读数"]},
            account={"equity": 100000},
            holdings=[{"code": "000001", "market_value": 10000}],
        )
        assert out["position"] is None
        assert "缺读数" in out["block_new_long_reasons"]

    def test_no_equity_blocks(self):
        out = rs.guard("2026-08-20", budget=_budget(), account={}, holdings=[])
        assert "未录入总权益" in out["block_new_long_reasons"]
        assert out["position"] is None

    def test_over_total_appends_block(self, monkeypatch):
        monkeypatch.setattr("duanxian.trade_calendar.prev_trade_date", lambda _d: None)
        holdings = [{"code": "000001", "name": "平安", "market_value": 80000, "pnl": 0}]
        out = rs.guard("2026-08-20", budget=_budget(), account={"equity": 100000}, holdings=holdings)
        assert out["position"]["over_total"] is True
        assert "总仓已达当前档 Cap_total" in out["block_new_long_reasons"]

    def test_daily_loss_hit(self, monkeypatch):
        monkeypatch.setattr("duanxian.trade_calendar.prev_trade_date", lambda _d: "2026-08-19")
        account = {
            "equity": 90000,
            "constants": {"daily_loss_limit": 0.02},
            "snapshots": {"2026-08-19": {"equity": 100000}},
        }
        out = rs.guard("2026-08-20", budget=_budget(), account=account, holdings=[])
        assert out["daily_loss"]["hit"] is True
        assert any("当日亏损限额" in x for x in out["block_new_long_reasons"])


@pytest.mark.unit
class TestSizePreview:
    def test_unavailable_budget(self):
        out = rs.size_preview(
            "2026-08-20",
            budget={"available": False, "reason": "缺读数"},
            account={"equity": 100000},
            stop_pct=0.05,
        )
        assert out["ok"] is False and "缺读数" in out["reason"]

    def test_uses_used_and_phase(self):
        holdings = [{"market_value": 10000}]
        out = rs.size_preview(
            "2026-08-20",
            budget=_budget(),
            account={"equity": 100000, "constants": {"risk_per_trade": 0.005}},
            holdings=holdings,
            stop_pct=0.05,
            boards=1,
        )
        assert out["ok"] is True
        assert out["used"] == 10000
        assert out["phase"] == "升温扩张"
        assert out["amount"] > 0
