"""仓位预算硬规则：定档、缺数据、Cap、单笔金额。"""

from __future__ import annotations

import pytest

from duanxian import trade_budget as tb


def _base(**kw):
    r = {
        "summary_ok": True,
        "money_ok": True,
        "promotion_ok": True,
        "limit_up": 50,
        "highest": 4,
        "highest_hist": [3, 4, 5],
        "broken_rate": 0.25,
        "money_median": 1.0,
        "promotion_1to2": 0.35,
        "deep_loss_5_rate": 0.1,
        "market_limit_down": 5,
        "up": 3000,
        "down": 2000,
        "index_pct": 0.5,
    }
    r.update(kw)
    return r


class TestClassify:
    def test_retreat_when_height_pressed_and_hurt(self):
        phase, reasons = tb.classify_rule_phase(_base(
            highest=3, highest_hist=[5, 6, 5], broken_rate=0.45,
        ))
        assert phase == "退潮杀伤"
        assert reasons

    def test_overheat_high_break(self):
        phase, _ = tb.classify_rule_phase(_base(
            highest=6, highest_hist=[5, 6], broken_rate=0.42, money_median=1.0,
        ))
        assert phase == "过热防守"

    def test_crowded(self):
        phase, _ = tb.classify_rule_phase(_base(
            highest=5, highest_hist=[4, 5], broken_rate=0.2, money_median=0.5,
        ))
        assert phase == "高潮拥挤"

    def test_ice(self):
        phase, _ = tb.classify_rule_phase(_base(
            highest=2, highest_hist=[2, 3], broken_rate=0.3,
            money_median=-1.2, promotion_1to2=0.1, limit_up=20,
        ))
        assert phase == "冰点观察"

    def test_never_auto_repair(self):
        """硬规则永不产出修复确认。"""
        for h in range(1, 8):
            phase, _ = tb.classify_rule_phase(_base(highest=h, money_median=2.0))
            assert phase != "修复确认"

    def test_warmup_default(self):
        phase, _ = tb.classify_rule_phase(_base(
            highest=4, highest_hist=[3, 4], broken_rate=0.2,
            money_median=0.8, promotion_1to2=0.3, limit_up=40,
        ))
        assert phase == "升温扩张"


class TestBuildBudget:
    def test_unavailable_when_money_missing(self):
        out = tb.build_budget(_base(money_ok=False, money_reason="样本不足"))
        assert out["available"] is False
        assert out["cap_total"] is None
        assert "样本不足" in (out["reason"] or "")

    def test_unavailable_when_broken_rate_none(self):
        out = tb.build_budget(_base(broken_rate=None))
        assert out["available"] is False

    def test_caps_low_end(self):
        out = tb.build_budget(_base(
            highest=4, highest_hist=[3, 4], broken_rate=0.2,
            money_median=0.8, index_pct=-0.5,  # 无背离
        ))
        assert out["available"]
        assert out["phase"] == "升温扩张"
        assert out["cap_total"] == 0.60
        assert out["cap_single"] == 0.10

    def test_width_divergence_demotes(self):
        out = tb.build_budget(_base(
            highest=4, highest_hist=[3, 4], broken_rate=0.2,
            money_median=-0.5,  # 转负
            index_pct=1.2, up=1500, down=2500,  # 指数涨、上涨弱
        ))
        assert out["available"]
        assert out["width_divergence"]["hit"] is True
        assert out["demoted"] is True
        assert out["phase"] == "高潮拥挤"  # 升温 → 降一档
        assert out["rule_phase"] == "升温扩张"

    def test_override_sets_phase(self):
        out = tb.build_budget(
            _base(
                highest=2, highest_hist=[2, 2], broken_rate=0.25,
                money_median=-1, promotion_1to2=0.1, limit_up=15,
            ),
            override_phase="修复确认",
            override_reason="龙头反包确认",
        )
        assert out["rule_phase"] == "冰点观察"
        assert out["phase"] == "修复确认"
        assert out["cap_total"] == 0.40
        assert out["override_reason"] == "龙头反包确认"

    def test_repair_proxy_hint_only(self):
        out = tb.build_budget(
            _base(
                highest=2, money_median=1.0, money_median_prev=-1.0,
                promotion_1to2=0.3, promotion_1to2_prev=0.1,
                market_limit_down=5, market_limit_down_prev=20,
                limit_up=15,
            ),
            prev_rule_phase="冰点观察",
        )
        assert out["phase"] == "冰点观察"  # 不自动升
        assert out["repair_proxy"]["met"] is True


class TestSizeAndPosition:
    def test_size_min_of_three(self):
        # equity 100万, cap_single 10% = 10万; risk 0.5%/5% = 10万; remain 60万
        r = tb.size_amount(1_000_000, 0.6, 0.1, 0, 0.005, 0.05, boards=1)
        assert r["ok"]
        assert r["amount"] == 100_000.0

    def test_size_risk_binds(self):
        # stop 2% → risk allows 0.5/2 * equity = 25万, but single cap 10万
        r = tb.size_amount(1_000_000, 0.6, 0.1, 0, 0.005, 0.02)
        assert r["amount"] == 100_000.0

    def test_board_discount_on_crowded(self):
        r = tb.size_amount(1_000_000, 0.4, 0.08, 0, 0.005, 0.05,
                           boards=2, phase="高潮拥挤")
        # single 8万 * 0.7 * 0.5 = 2.8万
        assert r["components"]["board_discount"] == pytest.approx(0.35)
        assert r["amount"] == pytest.approx(28_000.0)

    def test_position_breach(self):
        hs = [
            {"code": "000001", "name": "A", "market_value": 120_000, "pnl": -1000},
            {"code": "000002", "name": "B", "market_value": 50_000, "pnl": 500},
        ]
        pos = tb.position_vs_caps(hs, 1_000_000, 0.2, 0.05)
        assert pos["over_total"] is False  # 17% < 20%
        assert pos["per_name"][0]["over_single"] is True  # 12% > 5%

    def test_reduce_order_worst_first(self):
        hs = [
            {"code": "1", "name": "好", "market_value": 100_000, "pnl": 5000},
            {"code": "2", "name": "差", "market_value": 100_000, "pnl": -8000},
        ]
        # cap 10% = 10万, used 20万 → 需减 10万，先减「差」
        order = tb.reduce_order(hs, 1_000_000, 0.1)
        assert order[0]["code"] == "2"
        assert order[0]["action"] == "建议减仓"
        assert order[0]["suggest_cut"] == 100_000.0


class TestDemote:
    def test_floor(self):
        assert tb.demote("退潮杀伤") == "退潮杀伤"
        assert tb.demote("过热防守") == "退潮杀伤"
