"""环境条 —— `short_board.snapshot` 按日归档。"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestShortBoardArchive:
    """短线指标条按日归档：收盘后最后一次覆盖 = 次日昨日。"""

    @pytest.fixture(autouse=True)
    def _iso(self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        sb._cache.clear()
        monkeypatch.setattr(sb, "_CACHE_DIR", str(tmp_path))
        yield
        sb._cache.clear()

    def test_yesterday_from_archive(self, tmp_path):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-19", {
            "temperature": 55, "n_up": 2000, "broken_r": 30.0, "m_net": 1e9,
        })
        y = sb._build_yesterday("2026-08-19", {})
        assert y["temperature"] == 55
        assert y["n_up"] == 2000
        assert y["broken_r"] == 30.0

    def test_zr_fields_fill_when_archive_missing(self):
        from duanxian import short_board as sb

        y = sb._build_yesterday(None, {"_m_net_zr": 5e8, "_v_sh_zr": 1e11})
        assert y["m_net"] == 5e8
        assert y["v_sh"] == 1e11

    def test_qcj_row_maps_fields(self):
        from duanxian import short_board as sb

        row = sb._qcj_row({
            "date": "2026-08-21",
            "temperatureDegree": 31,
            "sentimentLevel": "退潮期",
            "leaderName": "汉森制药",
            "leaderDayTop": "3天3板",
            "limitUpCount": 54,
            "limitDownCount": 13,
            "mainThemes": ["机器人", "光电共封装CPO", "医药", "黄金"],
        })
        assert row["qcj_temp"] == 31
        assert row["qcj_level"] == "退潮期"
        assert row["qcj_leader"] == "汉森制药"
        assert row["qcj_leader_top"] == "3天3板"
        assert row["qcj_zt"] == 54
        assert row["qcj_dt"] == 13
        assert row["qcj_themes"] == ["机器人", "光电共封装CPO", "医药", "黄金"]

    def test_qcj_yesterday_prefers_api_history(self):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-20", {"qcj_temp": 99, "temperature": 40})
        y = sb._build_yesterday("2026-08-20", {
            "_qcj_yesterday": {
                "qcj_temp": 48,
                "qcj_level": "修复期",
                "qcj_leader": "昨日龙头",
            },
        })
        assert y["qcj_temp"] == 48
        assert y["qcj_level"] == "修复期"
        assert y["qcj_leader"] == "昨日龙头"
        assert y["temperature"] == 40

    def test_short_board_reads_archive_off_session(self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-21", {
            "temperature": 48, "n_up": 2505, "qcj_temp": 31,
        })
        monkeypatch.setattr(
            sb, "china_now",
            lambda: __import__("datetime").datetime(2026, 8, 22, 12, 30))
        monkeypatch.setattr(
            "duanxian.trade_calendar.resolve_as_of",
            lambda _t: ("2026-08-21", "2026-08-20", False))
        calls = {"merge": 0}

        def track_merge(as_of, prev):
            calls["merge"] += 1
            return {"temperature": 99}

        monkeypatch.setattr(sb, "_merge_today", track_merge)
        snap = sb.snapshot()
        assert snap.get("from_archive") is True
        assert snap["today"]["temperature"] == 48
        assert calls["merge"] == 0

    def test_weekend_snapshot_keeps_two_sessions_no_saturday_file(
            self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-20", {
            "temperature": 40, "n_up": 1800, "qcj_temp": 28,
        })
        monkeypatch.setattr(
            sb, "china_now",
            lambda: __import__("datetime").datetime(2026, 8, 22, 12, 30))
        monkeypatch.setattr(
            "duanxian.trade_calendar.resolve_as_of",
            lambda _t: ("2026-08-21", "2026-08-20", False))
        monkeypatch.setattr(sb, "_merge_today", lambda as_of, prev: {
            "temperature": 48, "n_up": 2505, "qcj_temp": 31,
            "_qcj_yesterday": {},
        })
        snap = sb.snapshot()
        assert snap["date"] == "2026-08-21"
        assert snap["prev_date"] == "2026-08-20"
        assert snap["is_live"] is False
        assert snap["today"]["temperature"] == 48
        assert snap["yesterday"]["temperature"] == 40
        assert not (tmp_path / "2026-08-22.json").exists()


@pytest.mark.unit
class TestVolumeRatios:
    """5/20 日量比：当日成交额 ÷ 此前 N 日均额。"""

    @pytest.fixture(autouse=True)
    def _iso(self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        sb._cache.clear()
        monkeypatch.setattr(sb, "_CACHE_DIR", str(tmp_path))
        yield
        sb._cache.clear()

    def test_ratio_vs_prev_ma(self, monkeypatch):
        from duanxian import short_board as sb

        amounts = {
            "2026-08-18": 100.0,
            "2026-08-19": 100.0,
            "2026-08-20": 100.0,
            "2026-08-21": 100.0,
            "2026-08-22": 100.0,
            "2026-08-25": 150.0,
        }
        monkeypatch.setattr(
            "duanxian.trade_calendar.trade_dates_ending_at",
            lambda end, n=10: [
                "2026-08-18", "2026-08-19", "2026-08-20",
                "2026-08-21", "2026-08-22", "2026-08-25",
            ][-n:],
        )
        assert sb._ratio_vs_prev_ma("2026-08-25", 150.0, 5, amounts) == 1.5
        assert sb._ratio_vs_prev_ma("2026-08-25", 150.0, 20, amounts) is None

    def test_attach_prefers_live_v_ca_and_archives(self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        days = [
            "2026-07-31", "2026-08-01",
            "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08",
            "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15",
            "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22",
            "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-29",
            "2026-09-01",
        ]
        for d in days[:-1]:
            sb._save_archive(d, {"v_ca": 100e8})  # 100 亿
        monkeypatch.setattr(
            "duanxian.trade_calendar.trade_dates_ending_at",
            lambda end, n=10: [d for d in days if d <= end][-n:],
        )
        monkeypatch.setattr(sb, "_collect_amount_yi_by_date", lambda: {
            d: 100.0 for d in days[:-1]
        })
        today = {"v_ca": 200e8}
        yesterday = {"v_ca": 100e8}
        sb._attach_volume_ratios("2026-09-01", "2026-08-29", today, yesterday)
        assert today["vol_ratio_5d"] == 2.0
        assert today["vol_ratio_20d"] == 2.0
        assert yesterday["vol_ratio_5d"] == 1.0
        assert yesterday["vol_ratio_20d"] == 1.0


@pytest.mark.unit
class TestZtDtFor:
    """情绪全景同口径：涨跌停优先趣财经。"""

    @pytest.fixture(autouse=True)
    def _iso(self, tmp_path, monkeypatch):
        from duanxian import short_board as sb

        sb._cache.clear()
        monkeypatch.setattr(sb, "_CACHE_DIR", str(tmp_path))
        yield
        sb._cache.clear()

    def test_prefers_archive_qcj(self, monkeypatch):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-25", {"qcj_zt": 47, "qcj_dt": 3, "n_sjdt": 99})
        monkeypatch.setattr(sb, "_fetch_qcj", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应打 API")))
        out = sb.zt_dt_for("2026-08-25")
        assert out["limit_up"] == 47
        assert out["limit_down"] == 3
        assert out["limit_down_source"] == "qcj_archive"

    def test_zero_is_kept(self, monkeypatch):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-25", {"qcj_zt": 40, "qcj_dt": 0})
        monkeypatch.setattr(sb, "_fetch_qcj", lambda *_a, **_k: {})
        out = sb.zt_dt_for("2026-08-25")
        assert out["limit_down"] == 0

    def test_api_then_longtou_fallback(self, monkeypatch):
        from duanxian import short_board as sb

        sb._save_archive("2026-08-25", {"n_sjzt": 50, "n_sjdt": 11})
        monkeypatch.setattr(sb, "_fetch_qcj", lambda *_a, **_k: {
            "today": {"qcj_zt": 47, "qcj_dt": None},
        })
        out = sb.zt_dt_for("2026-08-25")
        assert out["limit_up"] == 47
        assert out["limit_up_source"] == "qcj_api"
        assert out["limit_down"] == 11
        assert out["limit_down_source"] == "longtou_archive"
