"""风格轮动：假存档可测，不打东财网络。"""

from __future__ import annotations

import datetime
import json

import pytest

from duanxian.style_indices import assemble
from duanxian.style_rotation import (
    CLOSE_N,
    Z_N,
    apply_to_snapshot,
    close_extreme_keys,
    derive_rotation,
    excess_ranks,
    item_metrics,
    load_archive,
    save_archive,
    spearman_of_ranks,
    _close_label,
    _zscore,
)


def _q(pct, price=10.0, up=None, down=None):
    return {"change_pct": pct, "price": price, "up": up, "down": down, "code": "x"}


def _weekday_prev(date: str):
    d = datetime.datetime.strptime(date, "%Y-%m-%d")
    for i in range(1, 10):
        p = d - datetime.timedelta(days=i)
        if p.weekday() < 5:
            return p.strftime("%Y-%m-%d")
    return None


def _weekday_ending(end_date: str, n: int = 10):
    d = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    out = []
    cur = d
    guard = 0
    while len(out) < n and guard < 80:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y-%m-%d"))
        cur -= datetime.timedelta(days=1)
        guard += 1
    out.reverse()
    return out


def _hot(quotes: dict) -> dict:
    base = {"csi_all": _q(0.0)}
    base.update(quotes)
    return assemble(base)


@pytest.mark.unit
class TestArchive:
    def test_save_overwrite_and_load(self, tmp_path, monkeypatch):
        from duanxian import style_rotation as sr

        monkeypatch.setattr(sr, "_CACHE_DIR", str(tmp_path))
        save_archive("2026-09-17", {"sh": _q(-0.4, price=3800)})
        save_archive("2026-09-17", {"sh": _q(-0.1, price=3810)})
        got = load_archive("2026-09-17")
        assert got is not None
        assert got["sh"]["change_pct"] == pytest.approx(-0.1)
        assert got["sh"]["price"] == pytest.approx(3810)

    def test_missing_is_none_not_skip(self, tmp_path, monkeypatch):
        from duanxian import style_rotation as sr

        monkeypatch.setattr(sr, "_CACHE_DIR", str(tmp_path))
        save_archive("2026-09-17", {"sh": _q(1.0)})
        assert load_archive("2026-09-16") is None
        assert load_archive("2026-09-15") is None


@pytest.mark.unit
class TestHotspotChurn:
    def test_enter_leave(self):
        prev = _hot({
            "small": _q(5.0), "yzt_yz": _q(4.0), "ylb_yz": _q(3.0),
            "yzb": _q(2.0), "micro": _q(1.0), "new_high": _q(0.0),
        })
        this = _hot({
            "small": _q(0.0), "yzt_yz": _q(4.0), "ylb_yz": _q(3.0),
            "yzb": _q(2.0), "micro": _q(1.0), "new_high": _q(5.0),
        })
        rot = derive_rotation(this, prev, "2026-09-17", "2026-09-16", live_deferred=False)
        assert rot["status"] == "ok"
        assert rot["against"] == {"date": "2026-09-16"}
        assert rot["this"] == {"date": "2026-09-17"}
        assert rot["hotspot_enter"] == ["new_high"]
        assert rot["hotspot_leave"] == ["small"]
        assert "yzt_yz" not in rot["hotspot_enter"]
        assert "yzt_yz" not in rot["hotspot_leave"]

    def test_missing_prev_is_absent_does_not_use_earlier(self):
        this = _hot({"small": _q(1.0)})
        rot = derive_rotation(this, None, "2026-09-17", "2026-09-16", live_deferred=False)
        assert rot["status"] == "absent"
        assert rot["against"] is None
        assert rot["hotspot_enter"] == []

    def test_missing_csi_is_partial_keeps_dates(self):
        prev = assemble({"small": _q(1.0), "csi_all": _q(0.0)})
        this = assemble({"small": _q(2.0)})  # 缺中证全指
        rot = derive_rotation(this, prev, "2026-09-17", "2026-09-16", live_deferred=False)
        assert rot["status"] == "partial"
        assert rot["against"] == {"date": "2026-09-16"}
        assert rot["hotspot_enter"] == []
        assert rot["hotspot_leave"] == []


@pytest.mark.unit
class TestExcessRankAndDelta:
    def test_rank_rise_is_positive_and_excludes_benchmark(self):
        prev = _hot({"small": _q(3.0), "yzt_yz": _q(1.0), "sh": _q(9.0), "hsi": _q(8.0)})
        this = _hot({"small": _q(1.0), "yzt_yz": _q(3.0), "sh": _q(9.0), "hsi": _q(8.0)})
        pr, tr = excess_ranks(prev), excess_ranks(this)
        assert pr is not None and tr is not None
        assert "sh" not in pr and "hsi" not in pr and "csi_all" not in pr
        assert pr["small"] == 1 and pr["yzt_yz"] == 2
        assert tr["yzt_yz"] == 1 and tr["small"] == 2
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=[None] * Z_N, close_quotes=[None] * CLOSE_N,
        )
        assert m["yzt_yz"]["excess_rank_delta"] == 1
        assert m["small"]["excess_rank_delta"] == -1
        assert m["yzt_yz"]["change_pct_delta"] == pytest.approx(2.0)
        assert m["sh"]["excess_rank_delta"] is None
        assert m["sh"]["change_pct_delta"] == pytest.approx(0.0)

    def test_tie_uses_catalog_order(self):
        packed = _hot({"yzt_yz": _q(1.0), "yzt": _q(1.0), "ylb_yz": _q(1.0)})
        ranks = excess_ranks(packed)
        assert ranks is not None
        assert list(ranks)[:3] == ["yzt_yz", "yzt", "ylb_yz"]

    def test_missing_csi_either_side_no_rank(self):
        prev = assemble({"small": _q(1.0)})
        this = _hot({"small": _q(2.0)})
        assert excess_ranks(prev) is None
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=[None] * Z_N, close_quotes=[None] * CLOSE_N,
        )
        assert m["small"]["excess_rank_delta"] is None
        assert m["small"]["change_pct_delta"] == pytest.approx(1.0)

    def test_missing_prev_pct_delta_insufficient(self):
        prev = _hot({"yzt_yz": _q(1.0)})
        this = _hot({"small": _q(2.0), "yzt_yz": _q(1.0)})
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=[None] * Z_N, close_quotes=[None] * CLOSE_N,
        )
        assert m["small"]["change_pct_delta"] is None


@pytest.mark.unit
class TestSpearman:
    def test_same_order_is_one(self):
        a = {"small": 1, "yzt_yz": 2, "div_csi": 3}
        assert spearman_of_ranks(a, a)["value"] == pytest.approx(1.0)
        assert spearman_of_ranks(a, a)["n"] == 3
        assert spearman_of_ranks(a, a)["status"] == "ok"

    def test_full_reverse_is_negative(self):
        this = {"small": 1, "yzt_yz": 2, "div_csi": 3}
        prev = {"small": 3, "yzt_yz": 2, "div_csi": 1}
        out = spearman_of_ranks(this, prev)
        assert out["value"] == pytest.approx(-1.0)
        assert out["n"] == 3

    def test_too_few_overlap_is_insufficient(self):
        out = spearman_of_ranks({"small": 1}, {"small": 2, "yzt_yz": 1})
        assert out["status"] == "不足"
        assert out["value"] is None
        assert out["n"] == 1

    def test_missing_ranks_insufficient(self):
        out = spearman_of_ranks(None, {"small": 1})
        assert out["status"] == "不足"
        assert out["n"] == 0


@pytest.mark.unit
class TestZscoreAndCumExcess:
    def test_flat_window_z_is_zero(self):
        assert _zscore(1.0, [1.0] * Z_N) == pytest.approx(0.0)

    def test_hole_or_short_is_none(self):
        assert _zscore(1.0, [1.0] * 9 + [None]) is None
        assert _zscore(1.0, [1.0] * 9) is None

    def test_live_this_not_used_as_r(self):
        this = _hot({"small": _q(9.0)})
        prev = _hot({"small": _q(1.0)})
        window = [{"small": _q(1.0), "csi_all": _q(0.0)}] * Z_N
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=False,
            z_quotes=window, close_quotes=[None] * CLOSE_N,
        )
        assert m["small"]["zscore"] is None
        assert m["small"]["cum_excess"] is None
        assert m["small"]["change_pct_delta"] == pytest.approx(8.0)

    def test_cum_excess_skips_benchmark_and_needs_ten(self):
        this = _hot({"small": _q(2.0), "sh": _q(1.0)})
        prev = _hot({"small": _q(1.0), "sh": _q(0.5)})
        window = [{"small": _q(1.0), "sh": _q(0.5), "csi_all": _q(0.2)}] * Z_N
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=window, close_quotes=[None] * CLOSE_N,
        )
        assert m["small"]["cum_excess"] == pytest.approx(8.0)
        assert m["sh"]["cum_excess"] is None
        hole = list(window)
        hole[3] = None
        m2 = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=hole, close_quotes=[None] * CLOSE_N,
        )
        assert m2["small"]["cum_excess"] is None
        assert m2["small"]["zscore"] is None


@pytest.mark.unit
class TestCloseExtreme:
    def test_high_low_flat_and_hole(self):
        assert _close_label([float(i) for i in range(CLOSE_N)]) == "新高"
        assert _close_label([float(CLOSE_N - i) for i in range(CLOSE_N)]) == "新低"
        assert _close_label([10.0] * CLOSE_N) == "都不是"
        mid = [10.0] * (CLOSE_N - 1) + [10.5]
        assert _close_label(mid) == "新高"
        hole = [10.0] * (CLOSE_N - 1) + [None]
        assert _close_label(hole) == "不足"
        assert _close_label([10.0] * 5) == "不足"

    def test_reconstituted_baskets_not_reported(self):
        this = _hot({"yzt_yz": _q(1.0, price=100), "sh": _q(0.1, price=20), "csi2000": _q(0.2, price=30)})
        prev = _hot({"yzt_yz": _q(0.5, price=90), "sh": _q(0.0, price=19), "csi2000": _q(0.1, price=29)})
        closes = [{"yzt_yz": _q(0, price=10 + i), "sh": _q(0, price=10 + i),
                    "csi2000": _q(0, price=10 + i), "new_high": _q(0, price=10 + i)}
                   for i in range(CLOSE_N)]
        m = item_metrics(
            this_packed=this, prev_packed=prev, as_of_settled=True,
            z_quotes=[None] * Z_N, close_quotes=closes,
        )
        assert m["yzt_yz"]["close_extreme"] is None
        assert m["new_high"]["close_extreme"] is None
        assert "yzt_yz" not in close_extreme_keys()
        assert "new_high" not in close_extreme_keys()
        assert "small_growth" not in close_extreme_keys()
        assert "value_stock" not in close_extreme_keys()
        assert "cni_growth" in close_extreme_keys()
        assert "csi_tech" in close_extreme_keys()
        assert m["sh"]["close_extreme"] == "新高"
        assert m["csi2000"]["close_extreme"] == "新高"


@pytest.mark.unit
class TestApplySnapshot:
    @pytest.fixture(autouse=True)
    def _iso(self, monkeypatch, tmp_path):
        from duanxian import style_indices as si
        from duanxian import style_rotation as sr

        monkeypatch.setattr(sr, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(si.trade_calendar, "prev_trade_date", _weekday_prev)
        monkeypatch.setattr(si.trade_calendar, "trade_dates_ending_at", _weekday_ending)
        yield

    def test_settled_persists_unsettled_does_not(self, tmp_path):
        packed = assemble({"sh": _q(-0.41, price=3800), "csi_all": _q(-0.2)})
        apply_to_snapshot(packed, as_of="2026-09-17", prev="2026-09-16", settled=True)
        assert (tmp_path / "2026-09-17.json").is_file()
        live = assemble({"sh": _q(9.0, price=3900), "csi_all": _q(1.0)})
        apply_to_snapshot(live, as_of="2026-09-18", prev="2026-09-17", settled=False)
        assert not (tmp_path / "2026-09-18.json").exists()

    def test_live_uses_last_two_settled_not_live_quotes(self, tmp_path):
        six = {
            "csi_all": _q(0.0),
            "small": _q(5.0), "mid": _q(4.0), "large": _q(3.0),
            "micro": _q(2.0), "ylb_yz": _q(1.0), "yzt_yz": _q(0.0),
        }
        seven = {
            "csi_all": _q(0.0),
            "small": _q(0.0), "mid": _q(4.0), "large": _q(3.0),
            "micro": _q(2.0), "ylb_yz": _q(1.0), "yzt_yz": _q(5.0),
        }
        save_archive("2026-09-16", six)
        save_archive("2026-09-17", seven)
        live = assemble({"csi_all": _q(0.0), "small": _q(9.0), "new_high": _q(8.0)})
        out = apply_to_snapshot(live, as_of="2026-09-18", prev="2026-09-17", settled=False)
        rot = out["rotation"]
        assert rot["live_deferred"] is True
        assert rot["this"]["date"] == "2026-09-17"
        assert rot["against"]["date"] == "2026-09-16"
        assert rot["hotspot_enter"] == ["yzt_yz"]
        assert rot["hotspot_leave"] == ["small"]
        assert "new_high" not in rot["hotspot_enter"]
        small = next(it for g in out["groups"] for it in g["items"] if it["key"] == "small")
        assert small["change_pct"] == pytest.approx(9.0)
        assert small["change_pct_delta"] == pytest.approx(-5.0)
        assert small["zscore"] is None

    def test_missing_middle_session_not_skipped(self, tmp_path):
        save_archive("2026-09-15", {"csi_all": _q(0.0), "small": _q(1.0)})
        save_archive("2026-09-17", {"csi_all": _q(0.0), "small": _q(2.0)})
        packed = assemble({"csi_all": _q(0.0), "small": _q(2.0)})
        out = apply_to_snapshot(packed, as_of="2026-09-17", prev="2026-09-16", settled=True)
        assert out["rotation"]["status"] == "absent"
        assert out["rotation"]["against"] is None
        small = next(it for g in out["groups"] for it in g["items"] if it["key"] == "small")
        assert small["change_pct_delta"] is None


@pytest.mark.unit
class TestSnapshotWire:
    @pytest.fixture(autouse=True)
    def _iso(self, monkeypatch, tmp_path):
        from duanxian import style_indices as si
        from duanxian import style_rotation as sr

        si._reset_runtime_state()
        monkeypatch.setattr(sr, "_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(si.trade_calendar, "prev_trade_date", _weekday_prev)
        monkeypatch.setattr(si.trade_calendar, "trade_dates_ending_at", _weekday_ending)
        monkeypatch.setattr(si, "_load_quotes", lambda: {"sh": _q(-0.41), "csi_all": _q(-0.2)})
        monkeypatch.setattr(
            si.trade_calendar, "resolve_as_of",
            lambda _t=None: ("2026-09-17", "2026-09-16", False),
        )
        monkeypatch.setattr(si.trade_calendar, "is_settled", lambda _d: True)
        monkeypatch.setattr(si.trade_calendar, "ttl_until_session_boundary", lambda ttl: ttl)
        yield
        si._reset_runtime_state()

    def test_snapshot_writes_and_attaches_rotation(self, tmp_path):
        from duanxian.style_indices import snapshot

        save_archive("2026-09-16", {"sh": _q(0.1), "csi_all": _q(0.0), "small": _q(1.0)})
        out = snapshot()
        assert (tmp_path / "2026-09-17.json").is_file()
        assert out["rotation"]["status"] in {"ok", "partial"}
        assert out["rotation"]["against"]["date"] == "2026-09-16"
        raw = json.loads((tmp_path / "2026-09-17.json").read_text(encoding="utf-8"))
        assert "change_pct" in raw["quotes"]["sh"]
        assert "price" in raw["quotes"]["sh"]
