"""短线精灵引擎 —— 注入时钟与假 snapshot，只测对外行为。"""

from __future__ import annotations

import datetime as dt

import pytest

from duanxian import short_sprite as ss


class Clock:
    def __init__(self, when: dt.datetime):
        self.when = when

    def __call__(self) -> dt.datetime:
        return self.when

    def set(self, when: dt.datetime) -> None:
        self.when = when

    def add(self, **kwargs) -> None:
        self.when = self.when + dt.timedelta(**kwargs)


def _dt(h: int, m: int = 0, s: int = 0, day: int = 18) -> dt.datetime:
    return dt.datetime(2026, 9, day, h, m, s, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def _sb(**today):
    return {
        "date": "2026-09-18",
        "is_live": True,
        "settled": False,
        "today": dict(today),
    }


def _zt(consec=None):
    return {
        "date": "2026-09-18",
        "is_live": True,
        "settled": False,
        "consec_premium_avg": consec,
    }


def _res(score=None, trial=0.99):
    return {
        "date": "2026-09-18",
        "default": {"score": score},
        "trial": {"score": trial} if trial is not None else None,
    }


def _style(*items):
    return {
        "date": "2026-09-18",
        "is_live": True,
        "settled": False,
        "groups": [{"id": "g", "label": "组", "items": list(items)}],
        "unavailable": [{"key": "ths_emotion", "name": "同花顺情绪指数", "reason": "专有"}],
    }


def _item(key, name, change_pct, available=True):
    return {"key": key, "name": name, "change_pct": change_pct, "available": available}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    ss._reset_runtime_state()
    monkeypatch.setattr(ss, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ss, "_CONFIG_PATH", str(tmp_path / "short_sprite.json"))
    monkeypatch.setattr(ss, "_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(ss, "_STATE_PATH", str(tmp_path / "cache" / "state.json"))
    clock = Clock(_dt(10, 0, 0))
    monkeypatch.setattr(ss, "_now_fn", clock)
    feeds = {
        "sb": _sb(n_up=2000, n_down=1500, temperature=50, qcj_temp=40, zt_avg_zr=1.0),
        "zt": _zt(0.5),
        "res": _res(0.05),
        "st": _style(_item("zt_perf", "昨日涨停表现", 1.0), _item("small", "小盘股", 0.8)),
    }
    monkeypatch.setattr(ss, "_read_short_board", lambda: feeds["sb"])
    monkeypatch.setattr(ss, "_read_zt_effect", lambda: feeds["zt"])
    monkeypatch.setattr(ss, "_read_resonance", lambda: feeds["res"])
    monkeypatch.setattr(ss, "_read_style_indices", lambda: feeds["st"])
    yield {"clock": clock, "feeds": feeds, "tmp": tmp_path}
    ss._reset_runtime_state()


def _seq(snap, seq_id):
    return next(s for s in snap["sequences"] if s["id"] == seq_id)


@pytest.mark.unit
class TestWallClock:
    def test_next_slot_from_mid_slot(self):
        # 2026-09-18 10:00:07 CST = 1758160807 + 7? 用裸 Unix 秒更直观
        assert ss.unix_slot_start(1_000_007, 20) == 1_000_000
        assert ss.next_unix_slot(1_000_007, 20) == 1_000_020

    def test_exact_boundary_waits_full_slot(self):
        assert ss.unix_slot_start(1_000_000, 20) == 1_000_000
        assert ss.next_unix_slot(1_000_000, 20) == 1_000_020

    def test_delay_until_next(self):
        assert ss.delay_until_next_unix_slot(1_000_007.2, 20) == pytest.approx(12.8)


@pytest.mark.unit
class TestOpenAndSpeed:
    def test_no_open_before_0930(self, engine):
        engine["clock"].set(_dt(9, 15, 0))
        engine["feeds"]["zt"] = _zt(1.2)
        snap = ss.snapshot()
        seq = _seq(snap, "consec_premium")
        assert seq["open"] is None
        assert seq["current"] == pytest.approx(1.2)
        assert seq["vs_open"] is None

    def test_first_non_null_after_0930_is_open(self, engine):
        engine["clock"].set(_dt(9, 29, 50))
        engine["feeds"]["zt"] = _zt(0.4)
        ss.snapshot()
        engine["clock"].set(_dt(9, 30, 0))
        engine["feeds"]["zt"] = _zt(0.8)
        snap = ss.snapshot()
        seq = _seq(snap, "consec_premium")
        assert seq["open"] == pytest.approx(0.8)
        assert seq["vs_open"] == pytest.approx(0.0)

    def test_missing_quote_is_not_zero_open(self, engine):
        engine["feeds"]["zt"] = _zt(None)
        snap = ss.snapshot()
        seq = _seq(snap, "consec_premium")
        assert seq["current"] is None
        assert seq["open"] is None
        engine["feeds"]["zt"] = _zt(1.1)
        snap = ss.snapshot()
        assert _seq(snap, "consec_premium")["open"] == 1.1

    def test_speed_none_until_five_minutes(self, engine):
        engine["feeds"]["zt"] = _zt(1.0)
        snap = ss.snapshot()
        assert _seq(snap, "consec_premium")["speed"] is None
        engine["clock"].add(minutes=4, seconds=40)
        engine["feeds"]["zt"] = _zt(2.0)
        snap = ss.snapshot()
        assert _seq(snap, "consec_premium")["speed"] is None
        engine["clock"].add(seconds=30)
        engine["feeds"]["zt"] = _zt(2.5)
        snap = ss.snapshot()
        seq = _seq(snap, "consec_premium")
        assert seq["speed"] == pytest.approx(1.5)
        assert seq["speed_from"] == pytest.approx(1.0)


@pytest.mark.unit
class TestEdgesAndHysteresis:
    def _warm_speed(self, engine, start, then):
        engine["feeds"]["zt"] = _zt(start)
        ss.snapshot()
        engine["clock"].add(minutes=5)
        ss.snapshot()  # 点够了，先记下低于阈的涨速，边沿才有 prev
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(then)
        return ss.snapshot()

    def test_speed_edge_fires_once(self, engine):
        snap = self._warm_speed(engine, 0.0, 1.6)
        hits = [h for h in snap["new_hits"] if h["seq_id"] == "consec_premium"]
        assert len(hits) == 1
        assert hits[0]["event"] == "speed_up"
        assert hits[0]["speech"] == "连板溢价，涨速突破1.6%"
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(2.0)
        snap = ss.snapshot()
        extra = [h for h in snap["new_hits"] if h["seq_id"] == "consec_premium"]
        assert extra == []

    def test_hysteresis_blocks_second_until_return(self, engine):
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.1)
        snap = ss.snapshot()
        assert [h for h in snap["new_hits"] if h["event"] == "break_up"]
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.4)
        snap = ss.snapshot()
        assert [h for h in snap["new_hits"] if h["event"] == "break_up"] == []
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(2.6)  # <= 3.0 - 0.3，回差够了才再武装
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.2)
        snap = ss.snapshot()
        ups = [h for h in snap["new_hits"] if h["event"] == "break_up"]
        assert len(ups) == 1

    def test_breakout_and_breakdown_vs_open(self, engine):
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.1)
        snap = ss.snapshot()
        ups = [h for h in snap["new_hits"] if h["event"] == "break_up"]
        assert len(ups) == 1
        assert ups[0]["speech"] == "连板溢价，涨幅突破3.1%"
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.4)
        snap = ss.snapshot()
        assert [h for h in snap["new_hits"] if h["event"] == "break_up"] == []
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(-3.2)
        snap = ss.snapshot()
        downs = [h for h in snap["new_hits"] if h["event"] == "break_down"]
        assert len(downs) == 1
        assert downs[0]["speech"] == "连板溢价，涨幅跌破-3.2%"

    def test_unmonitored_does_not_hit(self, engine):
        ss.save_rules({"consec_premium": {"monitor": False}})
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(4.0)
        snap = ss.snapshot()
        assert [h for h in snap["hits"] if h["seq_id"] == "consec_premium"] == []
        seq = _seq(snap, "consec_premium")
        assert seq["open"] == pytest.approx(0.0)
        assert seq["current"] == pytest.approx(4.0)
        assert seq["monitored"] is False

    def test_stop_keeps_hits(self, engine):
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.5)
        snap = ss.snapshot()
        assert snap["hits"]
        n = len(snap["hits"])
        ss.set_enabled(False)
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(-4.0)
        snap = ss.snapshot()
        assert snap["enabled"] is False
        assert len(snap["hits"]) == n
        assert snap["new_hits"] == []

    def test_settled_does_not_hit(self, engine):
        engine["feeds"]["sb"] = {**_sb(), "is_live": True, "settled": True}
        engine["feeds"]["zt"] = {**_zt(4.0), "settled": True, "is_live": False}
        snap = ss.snapshot()
        assert snap["hits"] == []
        assert snap["can_detect"] is False


@pytest.mark.unit
class TestPersistRestart:
    def test_open_survives_restart_ring_does_not(self, engine):
        engine["feeds"]["zt"] = _zt(1.25)
        ss.snapshot()
        engine["clock"].add(minutes=5)
        engine["feeds"]["zt"] = _zt(1.4)
        ss.snapshot()
        path = engine["tmp"] / "cache" / "2026-09-18.json"
        assert path.is_file()
        ss._reset_runtime_state()
        snap = ss.snapshot()
        seq = _seq(snap, "consec_premium")
        assert seq["open"] == pytest.approx(1.25)
        assert seq["speed"] is None
        # 环不落盘：重启后只剩本拍一个点，没有重启前那 5 分钟
        assert len(seq["samples"]) == 1

    def test_new_session_does_not_carry_open(self, engine):
        engine["feeds"]["zt"] = _zt(1.0)
        ss.snapshot()
        for key in ("sb", "zt", "res", "st"):
            engine["feeds"][key] = dict(engine["feeds"][key])
            engine["feeds"][key]["date"] = "2026-09-22"
        engine["clock"].set(_dt(10, 0, 0, day=22))
        engine["feeds"]["zt"]["consec_premium_avg"] = 2.2
        snap = ss.snapshot()
        assert snap["date"] == "2026-09-22"
        assert _seq(snap, "consec_premium")["open"] == pytest.approx(2.2)
        assert all(h.get("seq_id") != "consec_premium" or True for h in snap["hits"])
        # 昨天的命中不应出现在新场次
        assert snap["hits"] == []


@pytest.mark.unit
class TestOtherSeries:
    def test_counts_temp_resonance_units(self, engine):
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["sb"] = _sb(n_up=2450, n_down=1000, temperature=66, qcj_temp=58, zt_avg_zr=1.0)
        engine["feeds"]["res"] = _res(0.46)
        snap = ss.snapshot()
        up = [h for h in snap["new_hits"] if h["seq_id"] == "env_n_up"]
        assert up and up[0]["speech"] == "环境条上涨数，涨幅突破450家"
        down = [h for h in snap["new_hits"] if h["seq_id"] == "env_n_down"]
        assert down and down[0]["direction"] == "down"
        assert down[0]["reversed"] is True
        temp = [h for h in snap["new_hits"] if h["seq_id"] == "temperature"]
        assert temp and temp[0]["speech"] == "情绪温度，涨幅突破16"
        res_hits = [h for h in snap["new_hits"] if h["seq_id"] == "resonance"]
        assert res_hits and res_hits[0]["speech"] == "打板情绪共振，涨幅突破0.410"

    def test_resonance_reads_default_not_trial(self, engine):
        engine["feeds"]["res"] = _res(score=0.05, trial=0.99)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["res"] = _res(score=0.10, trial=0.99)
        snap = ss.snapshot()
        seq = _seq(snap, "resonance")
        assert seq["current"] == pytest.approx(0.10)
        assert seq["vs_open"] == pytest.approx(0.05)
        assert [h for h in snap["hits"] if h["seq_id"] == "resonance"] == []

    def test_style_shared_threshold_individual_hits(self, engine):
        engine["feeds"]["st"] = _style(
            _item("zt_perf", "昨日涨停表现", 0.0),
            _item("finance", "金融", 0.0),
            _item("ghost", "幽灵", None, available=False),
        )
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["st"] = _style(
            _item("zt_perf", "昨日涨停表现", 3.2),
            _item("finance", "金融", 0.4),
            _item("ghost", "幽灵", 9.0, available=False),
        )
        snap = ss.snapshot()
        ids = {h["seq_id"] for h in snap["new_hits"]}
        assert "style:zt_perf" in ids
        assert "style:finance" not in ids
        assert "style:ghost" not in ids
        hit = next(h for h in snap["new_hits"] if h["seq_id"] == "style:zt_perf")
        assert hit["speech"] == "昨日涨停表现，涨幅突破3.2%"
        assert hit["name"] == "昨日涨停表现"
        names = {s["id"] for s in snap["sequences"]}
        assert "style:ghost" not in names
        assert "ths_emotion" not in names
        assert "style:ths_emotion" not in names

    def test_unavailable_catalog_stays_out(self, engine):
        engine["feeds"]["st"] = _style(
            _item("ths_emotion", "同花顺情绪指数", 4.0),
        )
        snap = ss.snapshot()
        ids = [s["id"] for s in snap["sequences"]]
        assert "style:ths_emotion" not in ids


@pytest.mark.unit
class TestConfigAndVoice:
    def test_reset_restores_factory(self, engine):
        ss.save_rules({"consec_premium": {"speed_up": 9.9, "monitor": False}})
        assert ss.resolved_rules()["consec_premium"]["speed_up"] == pytest.approx(9.9)
        ss.reset_rules()
        rule = ss.resolved_rules()["consec_premium"]
        assert rule["speed_up"] == pytest.approx(1.5)
        assert rule["monitor"] is True

    def test_voice_flag_on_hit(self, engine):
        ss.save_rules({"consec_premium": {"voice": False}})
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(3.3)
        snap = ss.snapshot()
        hit = next(h for h in snap["new_hits"] if h["seq_id"] == "consec_premium")
        assert hit["voice"] is False
        assert hit["speech"].startswith("连板溢价，")
