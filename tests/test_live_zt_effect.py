"""盘中昨涨停效应 —— `live_zt_effect.snapshot` 静态/动态分层缓存。"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestLiveZtEffectCache:
    @pytest.fixture(autouse=True)
    def _clear(self, tmp_path, monkeypatch):
        from duanxian import live_zt_effect as lze

        lze._reset_runtime_state()
        monkeypatch.setattr(lze, "_CACHE_DIR", str(tmp_path))
        yield
        lze._reset_runtime_state()

    def test_static_universe_and_open_gap_not_recomputed(self, monkeypatch):
        """昨涨停名单与开盘溢价属静态：同场次二次 snapshot 不得重打。"""
        from duanxian import live_zt_effect as lze

        univ_calls = []
        gap_calls = []
        pct_calls = []

        def fake_univ(as_of):
            univ_calls.append(as_of)
            return {
                "codes": ["000001", "000002", "600000"],
                "boards": {"000001": 1, "000002": 3, "600000": 2},
                "seed_rets": {"000001": 1.0, "000002": -6.0, "600000": 2.5},
            }

        def fake_gap(codes):
            gap_calls.append(tuple(codes))
            return {"000001": 0.5, "000002": -1.0, "600000": 1.2}

        def fake_pct(codes):
            pct_calls.append(tuple(codes))
            return {"000001": 1.0, "000002": -6.0, "600000": 2.5}

        monkeypatch.setattr(lze, "_fetch_universe", fake_univ)
        monkeypatch.setattr(
            "duanxian.emotion_metrics._batch_open_gap_live", fake_gap,
        )
        monkeypatch.setattr(
            "duanxian.emotion_metrics.batch_open_gap",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应退回 batch_open_gap")),
        )
        monkeypatch.setattr(
            "duanxian.emotion_metrics.batch_pct", fake_pct,
        )
        monkeypatch.setattr(
            lze.trade_calendar, "resolve_as_of",
            lambda today=None: ("2026-07-29", "2026-07-28", True),
        )
        monkeypatch.setattr(lze.trade_calendar, "is_settled", lambda d: False)
        monkeypatch.setattr(
            lze.trade_calendar, "should_write_daily_cache", lambda d: False,
        )

        a = lze.snapshot("2026-07-29")
        b = lze.snapshot("2026-07-29")

        assert a["available"] and b["available"]
        assert len(univ_calls) == 1, "静态宇宙被重复拉取"
        assert len(gap_calls) == 1, "开盘溢价被重复计算"
        assert a["open_success_rate"] == pytest.approx(2 / 3, abs=0.001)
        assert a["deep_loss_5_count"] == 1
        assert a["consec_premium_avg"] == pytest.approx((-6.0 + 2.5) / 2, abs=0.01)
        # 动态 TTL 内二次 snapshot 也不应重打涨跌幅
        assert len(pct_calls) == 1

    def test_settled_uses_seed_rets_without_batch_pct(self, monkeypatch):
        """已定稿：用宇宙种子涨跌幅，勿反复 batch_pct。"""
        from duanxian import live_zt_effect as lze

        pct_calls = []

        monkeypatch.setattr(
            lze, "_fetch_universe",
            lambda as_of: {
                "codes": ["000001", "000002"],
                "boards": {"000001": 2, "000002": 1},
                "seed_rets": {"000001": 3.0, "000002": -5.5},
            },
        )
        monkeypatch.setattr(
            "duanxian.emotion_metrics.batch_open_gap",
            lambda codes, date: {"000001": 1.0, "000002": -0.5},
        )
        monkeypatch.setattr(
            "duanxian.emotion_metrics.batch_pct",
            lambda codes: pct_calls.append(1) or {},
        )
        monkeypatch.setattr(lze.trade_calendar, "is_settled", lambda d: True)
        monkeypatch.setattr(
            lze.trade_calendar, "should_write_daily_cache", lambda d: False,
        )

        r = lze.snapshot("2026-07-29")
        assert r["available"]
        assert r["source"] == "settled"
        assert r["consec_premium_avg"] == 3.0
        assert r["deep_loss_5_count"] == 1
        assert pct_calls == [], "定稿场次仍打了 batch_pct"

    def test_archive_roundtrip_for_yesterday(self, tmp_path, monkeypatch):
        from duanxian import live_zt_effect as lze

        lze._save_archive("2026-07-28", {
            "open_success_rate": 0.4,
            "consec_premium_avg": 1.2,
            "deep_loss_5_count": 7,
            "sample": 100,
        })
        y = lze._yesterday_slice("2026-07-28")
        assert y["open_success_rate"] == 0.4
        assert y["deep_loss_5_count"] == 7
