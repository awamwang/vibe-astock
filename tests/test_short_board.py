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
