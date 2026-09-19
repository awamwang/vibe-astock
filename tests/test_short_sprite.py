"""短线精灵引擎 —— 注入时钟与假 snapshot，只测对外行为。"""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from duanxian import short_sprite as ss

_REAL_EMIT_HITS_HOOK = ss._emit_hits_hook


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
    monkeypatch.setattr(ss, "_emit_hits_hook", lambda view: None)
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
        assert hits[0]["from_value"] == pytest.approx(0.0)
        assert hits[0]["to_value"] == pytest.approx(1.6)
        assert hits[0]["from_ts"] == pytest.approx(ss._epoch(_dt(10, 0, 0)))
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
        assert "from_value" not in ups[0]
        assert "to_value" not in ups[0]
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

    def test_speed_window_survives_restart(self, engine):
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(minutes=5)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(1.6)
        snap = ss.snapshot()
        hit = next(h for h in snap["new_hits"] if h["seq_id"] == "consec_premium" and h["event"] == "speed_up")
        assert hit["from_value"] == pytest.approx(0.0)
        assert hit["to_value"] == pytest.approx(1.6)
        hit_id = hit["id"]
        ss._reset_runtime_state()
        snap = ss.snapshot()
        loaded = next(h for h in snap["hits"] if h["id"] == hit_id)
        assert loaded["from_value"] == pytest.approx(0.0)
        assert loaded["to_value"] == pytest.approx(1.6)
        assert loaded["from_ts"] == pytest.approx(ss._epoch(_dt(10, 0, 0)))

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
        assert temp and temp[0]["speech"] == "情绪温度，涨幅突破15"
        assert temp[0]["value"] == pytest.approx(15)
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

    def test_style_watch_skips_unlisted_indices(self, engine):
        engine["feeds"]["st"] = _style(
            _item("yzt_yz", "昨日涨停表现", 0.0),
            _item("small", "小盘股", 0.0),
            _item("small_growth", "小盘成长", 0.0),
            _item("bank", "银行", 0.0),
            _item("a50", "富时A50期指连续", 0.0),
            _item("csi_info", "全指信息", 0.0),
            _item("ghost", "幽灵", None, available=False),
        )
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["st"] = _style(
            _item("yzt_yz", "昨日涨停表现", 3.2),
            _item("small", "小盘股", 3.2),
            _item("small_growth", "小盘成长", 3.2),
            _item("bank", "银行", 3.2),
            _item("a50", "富时A50期指连续", 3.2),
            _item("csi_info", "全指信息", 3.2),
            _item("ghost", "幽灵", 9.0, available=False),
        )
        snap = ss.snapshot()
        ids = {h["seq_id"] for h in snap["new_hits"]}
        assert "style:yzt_yz" in ids
        assert "style:small" in ids
        assert "style:small_growth" in ids
        assert "style:bank" in ids
        assert "style:a50" in ids
        assert "style:csi_info" not in ids
        assert "style:ghost" not in ids
        names = {s["id"] for s in snap["sequences"]}
        assert "style:yzt_yz" in names
        assert "style:small" in names
        assert "style:small_growth" in names
        assert "style:bank" in names
        assert "style:a50" in names
        assert "style:csi_info" not in names
        assert "style:ghost" not in names
        assert "ths_emotion" not in names
        assert "style:ths_emotion" not in names
        small = _seq(snap, "style:small")
        assert small["group"] == "size"
        assert small["group_label"] == "市值风格"
        assert _seq(snap, "style:yzt_yz")["group_label"] == "打板风格"
        assert _seq(snap, "style:small_growth")["group_label"] == "其他"
        assert _seq(snap, "style:bank")["group_label"] == "金融板块"
        assert _seq(snap, "style:a50")["group_label"] == "外围对照"

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
        assert rule["speed_up"] == pytest.approx(0.5)
        assert rule["speed_down"] == pytest.approx(-0.5)
        assert rule["monitor"] is True
        zt = ss.resolved_rules()["zt_premium"]
        assert zt["speed_up"] == pytest.approx(0.5)
        assert zt["speed_down"] == pytest.approx(-0.5)
        res = ss.resolved_rules()["resonance"]
        assert res["speed_up"] == pytest.approx(0.1)
        assert res["speed_down"] == pytest.approx(-0.1)

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

    def test_export_includes_dedicated_style_watches(self, engine):
        from duanxian.style_indices import ITEMS

        cfg = ss.export_config()
        keys = [r["key"] for r in cfg["rules"]]
        assert keys[:2] == ["consec_premium", "zt_premium"]
        by_key = {r["key"]: r for r in cfg["rules"]}
        on_groups = {"board", "size", "attribute", "other"}
        off_groups = {"dividend", "benchmark"}
        extra_on = {
            "value_stock", "cni_growth", "cni_value", "csi_tech", "csi_cons",
            "bank", "ins", "sec", "tech_lead", "a50",
        }
        for it in ITEMS:
            if it.group in on_groups or it.group in off_groups or it.key in extra_on:
                assert it.key in keys
                assert it.key in cfg["defaults"]
                want_on = it.group not in off_groups
                assert cfg["defaults"][it.key]["monitor"] is want_on
                assert by_key[it.key]["monitor"] is want_on
                assert cfg["defaults"][it.key]["speed_up"] == pytest.approx(1.0)
                assert cfg["defaults"][it.key]["speed_down"] == pytest.approx(-1.0)
                assert cfg["defaults"][it.key]["break_up"] == pytest.approx(2.0)
                assert cfg["defaults"][it.key]["break_down"] == pytest.approx(-2.0)
                assert by_key[it.key]["label"] == it.name
            else:
                assert it.key not in keys
        assert "style_indices" not in keys
        assert "style_indices" not in cfg["defaults"]
        assert keys[len(ss.BOARD_SPECS)] == "yzt_yz"
        assert keys[-1] == "small_value"
        assert "csi_info" not in keys
        assert "hsi" not in keys
        assert by_key["consec_premium"]["group"] == "market"
        assert by_key["consec_premium"]["group_label"] == "盘面"
        assert by_key["yzt_yz"]["group_label"] == "打板风格"
        assert by_key["mid"]["group_label"] == "市值风格"
        assert by_key["low_price"]["group_label"] == "短线属性"
        assert by_key["value_stock"]["group_label"] == "风格类型"
        assert by_key["csi_tech"]["group_label"] == "风格类型"
        assert by_key["div_csi"]["group_label"] == "红利风格"
        assert by_key["cyb"]["group_label"] == "宽基指数"
        assert by_key["bank"]["group_label"] == "金融板块"
        assert by_key["tech_lead"]["group_label"] == "行业指数"
        assert by_key["a50"]["group_label"] == "外围对照"
        assert by_key["small_growth"]["group_label"] == "其他"

    def test_legacy_style_indices_rule_ignored(self, engine):
        merged = ss.save_rules({"style_indices": {"monitor": False}, "small": {"speed_up": 2.5}})
        assert "style_indices" not in merged
        assert merged["small"]["speed_up"] == pytest.approx(2.5)

    def test_dedicated_style_watch_independent(self, engine):
        ss.save_rules({"small": {"monitor": True}, "bank": {"monitor": False}})
        engine["feeds"]["st"] = _style(
            _item("small", "小盘股", 0.0),
            _item("bank", "银行", 0.0),
            _item("csi_info", "全指信息", 0.0),
        )
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["st"] = _style(
            _item("small", "小盘股", 3.2),
            _item("bank", "银行", 3.2),
            _item("csi_info", "全指信息", 3.2),
        )
        snap = ss.snapshot()
        ids = {h["seq_id"] for h in snap["new_hits"]}
        assert "style:small" in ids
        assert "style:bank" not in ids
        assert "style:csi_info" not in ids
        assert _seq(snap, "style:small")["monitored"] is True
        assert _seq(snap, "style:bank")["monitored"] is False
        assert _seq(snap, "style:small")["thresholds"]["speed_up"] == pytest.approx(1.0)
        assert _seq(snap, "style:small")["thresholds"]["break_up"] == pytest.approx(2.0)

    def test_benchmark_dividend_default_off_until_enabled(self, engine):
        engine["feeds"]["st"] = _style(
            _item("cyb", "创业板指", 0.0),
            _item("div_csi", "中证红利", 0.0),
            _item("yzt_yz", "昨日涨停表现", 0.0),
        )
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["st"] = _style(
            _item("cyb", "创业板指", 3.2),
            _item("div_csi", "中证红利", 3.2),
            _item("yzt_yz", "昨日涨停表现", 3.2),
        )
        snap = ss.snapshot()
        ids = {h["seq_id"] for h in snap["new_hits"]}
        assert "style:yzt_yz" in ids
        assert "style:cyb" not in ids
        assert "style:div_csi" not in ids
        assert _seq(snap, "style:cyb")["monitored"] is False
        assert _seq(snap, "style:div_csi")["monitored"] is False
        ss.save_rules({"cyb": {"monitor": True}, "div_csi": {"monitor": True}})
        ss._reset_runtime_state()
        engine["feeds"]["st"] = _style(
            _item("cyb", "创业板指", 0.0),
            _item("div_csi", "中证红利", 0.0),
        )
        ss.snapshot()
        engine["clock"].add(seconds=20)
        engine["feeds"]["st"] = _style(
            _item("cyb", "创业板指", 3.2),
            _item("div_csi", "中证红利", 3.2),
        )
        snap = ss.snapshot()
        ids = {h["seq_id"] for h in snap["new_hits"]}
        assert "style:cyb" in ids
        assert "style:div_csi" in ids


@pytest.mark.unit
class TestBreakLadder:
    def _set_temp(self, engine, temperature=50, qcj_temp=40):
        engine["feeds"]["sb"] = _sb(
            n_up=2000, n_down=1500, temperature=temperature,
            qcj_temp=qcj_temp, zt_avg_zr=1.0,
        )

    def test_rungs_math(self):
        assert ss._rungs_crossed_up(10, 16, 15) == [1]
        assert ss._rungs_crossed_up(10, 32, 15) == [1, 2]
        assert ss._rungs_crossed_up(16, 20, 15) == []
        assert ss._rungs_crossed_up(16, 31, 15) == [2]
        assert ss._rungs_crossed_up(None, 32, 15) == []
        assert ss._rungs_crossed_down(0, -16, -15) == [1]
        assert ss._rungs_crossed_down(0, -32, -15) == [1, 2]
        assert ss._rungs_crossed_down(-16, -20, -15) == []

    def test_second_rung_fires(self, engine):
        self._set_temp(engine, temperature=50)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=66)
        snap = ss.snapshot()
        first = [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_up"]
        assert len(first) == 1
        assert first[0]["value"] == pytest.approx(15)
        assert first[0]["speech"] == "情绪温度，涨幅突破15"
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=81)
        snap = ss.snapshot()
        second = [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_up"]
        assert len(second) == 1
        assert second[0]["value"] == pytest.approx(30)
        assert second[0]["speech"] == "情绪温度，涨幅突破30"

    def test_skip_fires_both_rungs(self, engine):
        self._set_temp(engine, temperature=50)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=82)
        snap = ss.snapshot()
        hits = [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_up"]
        assert [h["value"] for h in hits] == [pytest.approx(15), pytest.approx(30)]
        assert hits[1]["speech"] == "情绪温度，涨幅突破30"

    def test_second_rung_hysteresis(self, engine):
        self._set_temp(engine, temperature=50)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=82)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=78)  # vs=28, 30-3=27，30 档未回差
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=81)
        snap = ss.snapshot()
        assert [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_up"] == []
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=76)  # vs=26 <= 27，30 档回差
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=81)
        snap = ss.snapshot()
        hits = [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_up"]
        assert len(hits) == 1
        assert hits[0]["value"] == pytest.approx(30)

    def test_qcj_temp_ladder_and_premium_not(self, engine):
        self._set_temp(engine, qcj_temp=40)
        engine["feeds"]["zt"] = _zt(0.0)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, qcj_temp=72)
        engine["feeds"]["zt"] = _zt(6.2)
        snap = ss.snapshot()
        qcj = [h for h in snap["new_hits"] if h["seq_id"] == "qcj_temp" and h["event"] == "break_up"]
        assert [h["value"] for h in qcj] == [pytest.approx(15), pytest.approx(30)]
        prem = [h for h in snap["new_hits"] if h["seq_id"] == "consec_premium" and h["event"] == "break_up"]
        assert len(prem) == 1
        assert prem[0]["value"] == pytest.approx(6.2)
        engine["clock"].add(seconds=20)
        engine["feeds"]["zt"] = _zt(6.5)
        snap = ss.snapshot()
        extra = [h for h in snap["new_hits"] if h["seq_id"] == "consec_premium" and h["event"] == "break_up"]
        assert extra == []

    def test_down_ladder(self, engine):
        self._set_temp(engine, temperature=50)
        ss.snapshot()
        engine["clock"].add(seconds=20)
        self._set_temp(engine, temperature=18)
        snap = ss.snapshot()
        downs = [h for h in snap["new_hits"] if h["seq_id"] == "temperature" and h["event"] == "break_down"]
        assert [h["value"] for h in downs] == [pytest.approx(-15), pytest.approx(-30)]
        assert downs[1]["speech"] == "情绪温度，涨幅跌破-30"


def _break_premium(engine) -> None:
    engine["feeds"]["zt"] = _zt(0.0)
    ss.snapshot()
    engine["clock"].add(seconds=20)
    engine["feeds"]["zt"] = _zt(3.3)


@pytest.mark.unit
class TestPluginHook:
    def test_new_hits_call_emit_hook(self, engine, monkeypatch):
        seen: list[dict] = []
        monkeypatch.setattr(ss, "_emit_hits_hook", seen.append)
        _break_premium(engine)
        snap = ss.snapshot()
        hooked = [v for v in seen if v.get("new_hits")]
        assert hooked
        assert hooked[-1]["new_hits"][0]["seq_id"] == "consec_premium"
        assert hooked[-1]["new_hits"][0]["id"] == snap["new_hits"][0]["id"]

    def test_no_hits_skips_runner(self, engine, monkeypatch):
        from duanxian import hooks

        calls: list[int] = []

        class _Fake:
            def emit_short_sprite_hits(self, *args, **kwargs):
                calls.append(1)
                return 0

        monkeypatch.setattr(hooks, "RUNNER", _Fake())
        monkeypatch.setattr(ss, "_emit_hits_hook", _REAL_EMIT_HITS_HOOK)
        ss.snapshot()
        assert calls == []

    def test_hits_forward_to_runner(self, engine, monkeypatch):
        from duanxian import hooks

        calls: list[tuple[list, dict]] = []

        class _Fake:
            def emit_short_sprite_hits(self, hits, **kwargs):
                calls.append((list(hits), dict(kwargs)))
                return 1

        monkeypatch.setattr(hooks, "RUNNER", _Fake())
        monkeypatch.setattr(ss, "_emit_hits_hook", _REAL_EMIT_HITS_HOOK)
        _break_premium(engine)
        snap = ss.snapshot()
        assert calls
        hits, kwargs = calls[-1]
        assert hits[0]["id"] == snap["new_hits"][0]["id"]
        assert hits[0]["seq_id"] == "consec_premium"
        assert kwargs["date"] == "2026-09-18"
        assert kwargs["enabled"] is True
        assert kwargs["is_live"] is True
        assert kwargs["settled"] is False

    def test_hook_runs_outside_state_lock(self, engine, monkeypatch):
        acquired: list[bool] = []
        err: list[BaseException] = []

        def _hook(view):
            if not view.get("new_hits"):
                return
            try:
                ok = ss._STATE_LOCK.acquire(timeout=1.0)
                acquired.append(bool(ok))
                if ok:
                    ss._STATE_LOCK.release()
            except BaseException as exc:  # noqa: BLE001
                err.append(exc)

        monkeypatch.setattr(ss, "_emit_hits_hook", _hook)
        _break_premium(engine)
        t = threading.Thread(target=ss.snapshot)
        t.start()
        t.join(timeout=3)
        assert not t.is_alive()
        assert err == []
        assert acquired == [True]
