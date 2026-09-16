"""打板情绪共振：截面合成纯逻辑（不打网络）。"""

from __future__ import annotations

import math

import pytest

from duanxian.board_emotion_resonance import (
    DEFAULT_WEIGHT,
    LABEL_BAND,
    LAYER_KEYS,
    MIN_ACTIVE_LAYERS,
    MIN_BASELINE_N,
    coefficient,
    mean_sigma,
    score_board_emotion,
    weak_label,
)


def _full_current(**overrides):
    base = {
        "max_boards": 5.0,
        "promotion_rate": 0.5,
        "break_rate": 0.2,
        "zt_minus_dt": 40.0,
        "money_median": 1.0,
        "deep_loss_5_rate": 0.1,
    }
    base.update(overrides)
    return base


def _flat_window(n=10, **values):
    dates = [f"2026-08-{i:02d}" for i in range(1, n + 1)]
    window = {k: [values.get(k, 1.0)] * n for k in LAYER_KEYS}
    return dates, window


@pytest.mark.unit
class TestCoefficient:
    def test_at_mean_is_zero(self):
        assert coefficient(4.0, 4.0, 1.0, False) == 0.0

    def test_one_sigma_is_tanh_1(self):
        assert coefficient(5.0, 4.0, 1.0, False) == pytest.approx(math.tanh(1.0), abs=1e-6)

    def test_invert_flips_sign(self):
        pos = coefficient(0.5, 0.3, 0.1, False)
        neg = coefficient(0.5, 0.3, 0.1, True)
        assert pos is not None and neg is not None
        assert neg == pytest.approx(-pos)

    def test_sigma_near_zero_is_zero_not_missing(self):
        assert coefficient(7.0, 7.0, 0.0, False) == 0.0
        assert coefficient(7.0, 6.0, 1e-15, False) == 0.0

    def test_missing_value_is_none(self):
        assert coefficient(None, 1.0, 1.0, False) is None
        assert coefficient(1.0, None, 1.0, False) is None


@pytest.mark.unit
class TestMeanSigma:
    def test_does_not_fill_holes(self):
        mu, sig, n = mean_sigma([1.0, None, 3.0])  # type: ignore[list-item]
        assert n == 2
        assert mu == pytest.approx(2.0)

    def test_empty(self):
        mu, sig, n = mean_sigma([])
        assert mu is None and n == 0 and sig == 0.0


@pytest.mark.unit
class TestWeakLabel:
    def test_band(self):
        assert weak_label(LABEL_BAND) == "偏多"
        assert weak_label(-LABEL_BAND) == "偏空"
        assert weak_label(LABEL_BAND - 0.01) == "混杂"
        assert weak_label(None) == "不足"


@pytest.mark.unit
class TestScore:
    def test_equal_weights_average(self):
        dates, window = _flat_window(
            max_boards=4.0, promotion_rate=0.4, break_rate=0.3,
            zt_minus_dt=20.0, money_median=0.0, deep_loss_5_rate=0.2,
        )
        # 对照全相同 → σ=0 → 每层系数 0 → 分数 0 → 混杂
        out = score_board_emotion(_full_current(), window, dates)
        assert out["active_layers"] == 6
        assert out["score"] == 0.0
        assert out["label"] == "混杂"

    def test_one_sigma_up_on_all_non_invert(self):
        dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
        # 窗：0..9 的均值 4.5、σ=stdev
        series = [float(i) for i in range(10)]
        mu, sig, n = mean_sigma(series)
        assert n == 10 and mu is not None and sig > 0
        window = {k: list(series) for k in LAYER_KEYS}
        current = {k: mu + sig for k in LAYER_KEYS}
        out = score_board_emotion(current, window, dates)
        # 非 invert 四层 tanh(1)；invert 两层 tanh(-1)。等权 → 互相抵消一部分
        t = math.tanh(1.0)
        expected = (4 * t + 2 * (-t)) / 6
        assert out["score"] == pytest.approx(expected, abs=1e-5)

    def test_fewer_than_four_layers_is_insufficient(self):
        dates, window = _flat_window()
        current = {k: None for k in LAYER_KEYS}
        current["max_boards"] = 5.0
        current["promotion_rate"] = 0.4
        current["break_rate"] = 0.2
        out = score_board_emotion(current, window, dates)
        assert out["active_layers"] == 3
        assert out["score"] is None
        assert out["label"] == "不足"
        assert "有效层" in (out["reason"] or "")

    def test_short_window_marks_layer_missing(self):
        dates = [f"2026-08-{i:02d}" for i in range(1, 5)]  # 4 天 < 5
        window = {k: [1.0] * 4 for k in LAYER_KEYS}
        out = score_board_emotion(_full_current(), window, dates)
        assert out["score"] is None
        assert all(not ly["included"] for ly in out["layers"])
        assert any("对照不足" in r for r in out["layers"][0]["missing_reasons"])

    def test_holes_are_annotated_not_filled(self):
        dates, window = _flat_window()
        window["break_rate"] = [0.2] * 7 + [None, None, None]
        out = score_board_emotion(_full_current(), window, dates)
        br = next(ly for ly in out["layers"] if ly["key"] == "break_rate")
        assert br["n"] == 7
        assert br["included"] is True
        assert "2026-08-08" in br["missing_dates"]
        assert None in br["window_values"]

    def test_too_many_holes_drops_layer(self):
        dates, window = _flat_window()
        window["money_median"] = [1.0] * (MIN_BASELINE_N - 1) + [None] * (10 - MIN_BASELINE_N + 1)
        out = score_board_emotion(_full_current(), window, dates)
        money = next(ly for ly in out["layers"] if ly["key"] == "money_median")
        assert money["included"] is False
        assert money["n"] == MIN_BASELINE_N - 1

    def test_weight_zero_excluded(self):
        dates, window = _flat_window()
        weights = {k: DEFAULT_WEIGHT for k in LAYER_KEYS}
        weights["max_boards"] = 0
        out = score_board_emotion(_full_current(), window, dates, weights=weights)
        height = next(ly for ly in out["layers"] if ly["key"] == "max_boards")
        assert height["included"] is False
        assert out["active_layers"] == 5

    def test_baseline_override_does_not_change_sigma(self):
        dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
        series = [float(i) for i in range(10)]
        window = {k: list(series) for k in LAYER_KEYS}
        _mu, sig, _n = mean_sigma(series)
        out = score_board_emotion(
            _full_current(max_boards=9.0),
            window, dates,
            baselines={"max_boards": 0.0},
            trial=True,
        )
        height = next(ly for ly in out["layers"] if ly["key"] == "max_boards")
        assert height["baseline_overridden"] is True
        assert height["baseline"] == 0.0
        assert height["sigma"] == pytest.approx(sig)
        assert out["trial"] is True

    def test_override_cannot_include_short_window_layer(self):
        dates = [f"2026-08-{i:02d}" for i in range(1, 5)]  # 4 天 < 5
        window = {k: [1.0] * 4 for k in LAYER_KEYS}
        out = score_board_emotion(
            _full_current(), window, dates,
            baselines={k: 99.0 for k in LAYER_KEYS},
        )
        assert all(not ly["included"] for ly in out["layers"])
        assert out["score"] is None
        assert out["label"] == "不足"

    def test_seal_rate_is_not_a_layer(self):
        from duanxian.board_emotion_resonance import LAYERS
        assert "seal_rate" not in LAYER_KEYS
        assert "封板率" not in [s["label"] for s in LAYERS]
        invert = {s["key"] for s in LAYERS if s["invert"]}
        assert invert == {"break_rate", "deep_loss_5_rate"}


@pytest.mark.unit
class TestBaselineWindow:
    def test_baseline_dates_excludes_as_of(self, monkeypatch):
        from duanxian import board_emotion_resonance as ber

        as_of = "2026-09-15"
        raw = [f"2026-09-{i:02d}" for i in range(2, 16)]  # 含本场
        monkeypatch.setattr(
            ber.trade_calendar, "trade_dates_ending_at",
            lambda end, n=10: raw[-n:],
        )
        dates = ber.baseline_dates(as_of, 10)
        assert as_of not in dates
        assert all(d < as_of for d in dates)
        assert len(dates) == 10

    def test_snapshot_window_excludes_current_session(self, monkeypatch):
        from datetime import datetime

        from duanxian import board_emotion_resonance as ber

        as_of = "2026-09-15"
        window_dates = [f"2026-09-{i:02d}" for i in range(1, 15)]
        seen: list[str] = []

        def fake_readings(date, live_snap=None):
            seen.append(date)
            return {k: 1.0 for k in LAYER_KEYS}

        ber._reset_runtime_state()
        monkeypatch.setattr(ber, "china_now", lambda: datetime(2026, 9, 16, 12, 0))
        monkeypatch.setattr(ber, "day_readings", fake_readings)
        monkeypatch.setattr(ber, "baseline_dates", lambda d, n=10: list(window_dates))
        monkeypatch.setattr(
            "duanxian.live_emotion.snapshot",
            lambda _as_of=None: {"available": True, "date": as_of, "phase": "收盘"},
        )

        out = ber.snapshot(as_of)
        assert as_of not in out["window_dates"]
        assert out["window_dates"] == window_dates
        hist = [d for d in seen if d != as_of]
        assert as_of not in hist
        assert set(hist) == set(window_dates)

    def test_snapshot_trial_does_not_change_default(self, monkeypatch):
        from datetime import datetime

        from duanxian import board_emotion_resonance as ber

        as_of = "2026-09-15"
        window_dates = [f"2026-09-{i:02d}" for i in range(1, 11)]
        ber._reset_runtime_state()
        monkeypatch.setattr(ber, "china_now", lambda: datetime(2026, 9, 16, 12, 0))
        monkeypatch.setattr(
            ber, "day_readings",
            lambda date, live_snap=None: {k: 1.0 for k in LAYER_KEYS},
        )
        monkeypatch.setattr(ber, "baseline_dates", lambda d, n=10: list(window_dates))
        monkeypatch.setattr(
            "duanxian.live_emotion.snapshot",
            lambda _as_of=None: {"available": True, "date": as_of, "phase": "收盘"},
        )

        out = ber.snapshot(
            as_of,
            baselines={"max_boards": 0.0},
            weights={"break_rate": 0},
        )
        assert out["trial"] is not None
        height_d = next(ly for ly in out["default"]["layers"] if ly["key"] == "max_boards")
        height_t = next(ly for ly in out["trial"]["layers"] if ly["key"] == "max_boards")
        assert height_d["baseline_overridden"] is False
        assert height_t["baseline_overridden"] is True
        zb_d = next(ly for ly in out["default"]["layers"] if ly["key"] == "break_rate")
        zb_t = next(ly for ly in out["trial"]["layers"] if ly["key"] == "break_rate")
        assert zb_d["weight"] == DEFAULT_WEIGHT
        assert zb_t["included"] is False
        assert out["default"]["trial"] is False
        assert out["trial"]["trial"] is True


@pytest.mark.unit
class TestHttpContract:
    def _client(self, monkeypatch):
        from fastapi.testclient import TestClient

        import server
        from duanxian import board_emotion_resonance as ber

        captured: list[dict] = []

        def fake_snap(as_of=None, baselines=None, weights=None):
            captured.append({"as_of": as_of, "baselines": baselines, "weights": weights})
            default = {
                "trial": False, "score": 0.1, "label": "混杂",
                "reason": None, "active_layers": 6, "layers": [],
            }
            trial = None
            if baselines or weights:
                trial = {
                    "trial": True, "score": 0.9, "label": "偏多",
                    "reason": None, "active_layers": 6, "layers": [],
                }
            return {
                "available": True,
                "date": as_of or "2026-09-15",
                "window_dates": ["2026-09-01"],
                "note": "混算",
                "default": default,
                "trial": trial,
            }

        monkeypatch.setattr(server.board_emotion_resonance, "snapshot", fake_snap)
        monkeypatch.setattr(ber, "snapshot", fake_snap)
        return TestClient(server.app), captured

    def test_get_returns_default_without_trial(self, monkeypatch):
        c, captured = self._client(monkeypatch)
        r = c.get("/api/market/board-emotion-resonance")
        assert r.status_code == 200
        body = r.json()
        assert body["default"]["trial"] is False
        assert body["trial"] is None
        assert captured == [{"as_of": None, "baselines": None, "weights": None}]

    def test_post_returns_trial_and_keeps_default(self, monkeypatch):
        c, captured = self._client(monkeypatch)
        r = c.post("/api/market/board-emotion-resonance", json={
            "date": "2026-09-15",
            "baselines": {"max_boards": 0},
            "weights": {"break_rate": 0},
        })
        assert r.status_code == 200
        body = r.json()
        assert body["default"]["score"] == 0.1
        assert body["trial"]["trial"] is True
        assert body["trial"]["score"] == 0.9
        assert captured[-1]["baselines"] == {"max_boards": 0}
        assert captured[-1]["weights"] == {"break_rate": 0}

        g = c.get("/api/market/board-emotion-resonance?date=2026-09-15")
        assert g.json()["trial"] is None
        assert g.json()["default"]["score"] == 0.1

    def test_invalid_date_rejected(self, monkeypatch):
        c, _captured = self._client(monkeypatch)
        assert c.get("/api/market/board-emotion-resonance?date=not-a-date").status_code == 400
        assert c.post(
            "/api/market/board-emotion-resonance", json={"date": "2099-01-01"},
        ).status_code == 400

    def test_foreign_origin_post_rejected(self, monkeypatch):
        c, captured = self._client(monkeypatch)
        r = c.post(
            "/api/market/board-emotion-resonance",
            json={"baselines": {"max_boards": 1}},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403
        assert captured == []


@pytest.mark.unit
class TestFrontendSurfaces:
    def test_sidebar_and_route(self):
        import pathlib

        layout = pathlib.Path("frontend/src/components/layout/Layout.tsx").read_text(encoding="utf-8")
        router = pathlib.Path("frontend/src/router.tsx").read_text(encoding="utf-8")
        assert '{ to: "/short-resonance"' in layout
        assert 'label: "短线共振"' in layout
        assert 'path: "/short-resonance"' in router
        assert "ShortResonance" in router

    def test_short_board_only_reads_default(self):
        import pathlib

        src = pathlib.Path("frontend/src/pages/ShortBoard.tsx").read_text(encoding="utf-8")
        assert "fetchBoardEmotionResonance" in src
        assert "trialBoardEmotionResonance" not in src
        assert "恢复默认" not in src
        assert "/short-resonance" in src
        assert "#board-emotion" in src

    def test_resonance_page_has_trial_and_no_cycle_machine(self):
        import pathlib

        src = pathlib.Path("frontend/src/pages/ShortResonance.tsx").read_text(encoding="utf-8")
        assert "打板情绪共振" in src
        assert "短线共振" in src
        assert "trialBoardEmotionResonance" in src
        assert "恢复默认" in src
        assert "十日基线" in src
        assert "东财四池" in src or "混算" in src
        assert "六档" not in src
        assert "仓位建议" not in src
        assert "id=\"board-emotion\"" in src or "id='board-emotion'" in src
