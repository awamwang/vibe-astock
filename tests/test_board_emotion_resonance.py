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

    def test_current_session_not_passed_in_window(self):
        """对照窗由调用方提供；本场不得出现在 window_dates。"""
        dates, window = _flat_window()
        assert "2026-08-18" not in dates
        out = score_board_emotion(_full_current(), window, dates)
        assert out["active_layers"] >= MIN_ACTIVE_LAYERS
