"""合成情绪分 S：算法配置 + 分位合成。"""

from __future__ import annotations

import pytest

from duanxian import sentiment_score as ss
from duanxian import trade_budget as tb


@pytest.fixture
def iso_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_CONFIG_PATH", str(tmp_path / "sentiment_s.json"))
    monkeypatch.setattr(ss, "_SERIES_PATH", str(tmp_path / "series.json"))
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "series.db"))
    monkeypatch.setattr(ss, "_FUSION_CACHE_PATH", str(tmp_path / "fusionintel.json"))
    yield


@pytest.mark.unit
class TestSentimentScoreConfig:
    def test_default_hard_rules(self, iso_cfg):
        assert ss.get_method() == ss.METHOD_HARD
        cfg = ss.export_config()
        assert len(cfg["methods"]) == 4
        assert cfg["method"] == ss.METHOD_HARD
        assert cfg["has_fusionintel_api_key"] is False
        assert any(m["id"] == ss.METHOD_FUSION and m["needs_api_key"] for m in cfg["methods"])

    def test_set_method(self, iso_cfg):
        out = ss.set_method(ss.METHOD_PCT)
        assert out["method"] == ss.METHOD_PCT
        assert ss.get_method() == ss.METHOD_PCT

    def test_reject_unknown(self, iso_cfg):
        with pytest.raises(ss.SentimentScoreError):
            ss.set_method("nope")

    def test_fusionintel_requires_api_key(self, iso_cfg):
        with pytest.raises(ss.SentimentScoreError, match="API Key"):
            ss.set_method(ss.METHOD_FUSION)

    def test_fusionintel_saves_api_key(self, iso_cfg):
        out = ss.set_method(ss.METHOD_FUSION, fusionintel_api_key="sk_test_abcdefgh")
        assert out["method"] == ss.METHOD_FUSION
        assert out["has_fusionintel_api_key"] is True
        assert "sk_t" in out["fusionintel_api_key_masked"]
        # 完整 Key 不出现在导出里（掩码可含末 4 位）
        assert "sk_test_abcdefgh" not in str(out)
        assert ss.get_fusionintel_api_key() == "sk_test_abcdefgh"
        # 再保存其它算法时保留 Key；切回 FusionIntel 可不重填
        ss.set_method(ss.METHOD_HARD)
        assert ss.get_fusionintel_api_key() == "sk_test_abcdefgh"
        out2 = ss.set_method(ss.METHOD_FUSION)
        assert out2["method"] == ss.METHOD_FUSION


@pytest.mark.unit
class TestPercentileScore:
    def test_percentile_from_series(self, iso_cfg, monkeypatch):
        rows = []
        for i, (zt, dt, h, br, temp) in enumerate([
            (20, 30, 2, 0.5, 10),
            (40, 10, 3, 0.3, 40),
            (60, 5, 4, 0.2, 60),
            (80, 2, 5, 0.1, 80),
            (100, 0, 6, 0.05, 95),
        ]):
            rows.append({
                "date": f"2026-08-{10 + i:02d}",
                "limit_up": zt, "limit_down": dt, "highest": h,
                "broken_rate": br, "qcj_temp": temp, "em_ok": True,
            })
        ss._save_series(rows)
        monkeypatch.setattr(ss, "_enrich_one", lambda _d: {"highest": 6, "broken_rate": 0.05, "em_ok": True})
        out = ss.score_for("2026-08-14", method=ss.METHOD_PCT)
        assert out["available"] is True
        assert out["s"] is not None
        assert out["s"] > 70  # 序列里最热的一天

    def test_qcj_degree(self, iso_cfg):
        ss._save_series([{
            "date": "2026-08-25", "qcj_temp": 42,
            "limit_up": 47, "limit_down": 3, "highest": 5, "broken_rate": 0.2, "em_ok": True,
        }])
        out = ss.score_for("2026-08-25", method=ss.METHOD_QCJ)
        assert out["available"] and out["s"] == 42


@pytest.mark.unit
class TestRefreshSeriesEnrichOrder:
    def test_newest_first_and_bulk_miss(self, iso_cfg, monkeypatch):
        """从新往旧补；成功后更早空窗直接记 miss，避免卡在旧日。"""
        qcj = [
            {"date": "2026-08-01", "qcj_temp": 10, "limit_up": 20, "limit_down": 5, "consec_boards": 1},
            {"date": "2026-08-10", "qcj_temp": 20, "limit_up": 30, "limit_down": 4, "consec_boards": 2},
            {"date": "2026-08-20", "qcj_temp": 40, "limit_up": 50, "limit_down": 2, "consec_boards": 3},
            {"date": "2026-08-25", "qcj_temp": 50, "limit_up": 60, "limit_down": 1, "consec_boards": 4},
        ]
        monkeypatch.setattr(ss, "_fetch_qcj_rows", lambda: qcj)

        from duanxian import market_series as ms

        monkeypatch.setattr(ms, "ensure_fresh", lambda: {"ok": True, "skipped": True})
        monkeypatch.setattr(ms, "margin_map", lambda: {})
        monkeypatch.setattr(ms, "amount_metrics_map", lambda: {})

        order: list[str] = []

        def fake_enrich(d: str):
            order.append(d)
            if d >= "2026-08-20":
                return {"highest": 5, "broken_rate": 0.2, "em_ok": True}
            return {"highest": None, "broken_rate": None, "em_ok": False}

        monkeypatch.setattr(ss, "_enrich_one", fake_enrich)
        out = ss.refresh_series(enrich_limit=30)
        assert order == ["2026-08-25", "2026-08-20", "2026-08-10", "2026-08-01"]
        assert out["enriched_this_run"] == 2
        meta = out["meta"]
        assert meta["enriched_days"] == 2
        assert meta["miss_days"] == 2
        assert meta["pending_days"] == 0
        rows = {r["date"]: r for r in ss._load_series()["rows"]}
        assert rows["2026-08-25"]["em_ok"] is True
        assert rows["2026-08-01"]["em_miss"] is True

    def test_skip_em_miss_outside_recent_window(self, iso_cfg, monkeypatch):
        """非近窗的 em_miss 不再重试。"""
        qcj = [
            {"date": f"2026-07-{d:02d}", "qcj_temp": 10, "limit_up": 20, "limit_down": 5, "consec_boards": 1}
            for d in range(1, 11)
        ] + [
            {"date": f"2026-08-{d:02d}", "qcj_temp": 40, "limit_up": 50, "limit_down": 2, "consec_boards": 3}
            for d in range(18, 26)
        ]
        monkeypatch.setattr(ss, "_fetch_qcj_rows", lambda: qcj)
        from duanxian import market_series as ms

        monkeypatch.setattr(ms, "ensure_fresh", lambda: {"ok": True, "skipped": True})
        monkeypatch.setattr(ms, "margin_map", lambda: {})
        monkeypatch.setattr(ms, "amount_metrics_map", lambda: {})
        saved = []
        for row in qcj:
            if row["date"].startswith("2026-07"):
                saved.append({**row, "em_ok": False, "em_miss": True, "highest": None, "broken_rate": None})
            else:
                saved.append({**row, "em_ok": True, "em_miss": False, "highest": 5, "broken_rate": 0.1})
        ss._save_series(saved)
        called: list[str] = []
        monkeypatch.setattr(
            ss,
            "_enrich_one",
            lambda d: called.append(d) or {"highest": 5, "broken_rate": 0.1, "em_ok": True},
        )
        out = ss.refresh_series(enrich_limit=30)
        assert called == []
        assert out["enriched_this_run"] == 0
        assert out["meta"]["enriched_days"] == 8
        assert out["meta"]["miss_days"] == 10

    def test_score_from_cache(self, iso_cfg, monkeypatch):
        ss.set_method(ss.METHOD_FUSION, fusionintel_api_key="sk_unit_test")
        monkeypatch.setattr(
            ss,
            "_fusion_rows_for_score",
            lambda _key: [
                {"date": "2026-08-22", "s": 33.0, "price": 3000.0},
                {"date": "2026-08-25", "s": 41.5, "price": 3100.0},
            ],
        )
        out = ss.score_for("2026-08-25", method=ss.METHOD_FUSION)
        assert out["available"] is True
        assert out["s"] == 41.5
        assert out["method"] == ss.METHOD_FUSION

    def test_score_falls_back_to_prior_day(self, iso_cfg, monkeypatch):
        ss.set_method(ss.METHOD_FUSION, fusionintel_api_key="sk_unit_test")
        monkeypatch.setattr(
            ss,
            "_fusion_rows_for_score",
            lambda _key: [{"date": "2026-08-22", "s": 28.0, "price": None}],
        )
        out = ss.score_for("2026-08-25", method=ss.METHOD_FUSION)
        assert out["available"] is True
        assert out["s"] == 28.0
        assert out["data_date"] == "2026-08-22"

    def test_missing_key(self, iso_cfg):
        out = ss.score_for("2026-08-25", method=ss.METHOD_FUSION)
        assert out["available"] is False
        assert "API Key" in out["reason"]


@pytest.mark.unit
class TestClassifyWithS:
    def test_s_bands(self):
        base = {
            "highest": 4, "broken_rate": 0.2, "money_median": 1.0,
            "promotion_1to2": 0.3, "highest_hist": [3, 4, 4],
        }
        assert ss.classify_with_s(base, 15)[0] == "冰点观察"
        assert ss.classify_with_s(base, 40)[0] == "升温扩张"
        assert ss.classify_with_s(base, 70)[0] == "高潮拥挤"
        assert ss.classify_with_s(base, 85)[0] == "过热防守"

    def test_overlay_beats_s(self):
        readings = {
            "highest": 3, "broken_rate": 0.45, "money_median": -2,
            "promotion_1to2": 0.1, "highest_hist": [5, 5, 4, 4, 3],
            "deep_loss_5_rate": 0.3,
        }
        phase, _ = ss.classify_with_s(readings, 50)
        assert phase == "退潮杀伤"

    def test_classify_rule_uses_s_when_ok(self):
        readings = {
            "s": 40, "s_ok": True, "s_method": ss.METHOD_PCT,
            "highest": 4, "broken_rate": 0.2, "money_median": -1,
            "promotion_1to2": 0.14, "limit_up": 46,
            "highest_hist": [4, 4, 3, 4, 3],
        }
        phase, reasons = tb.classify_rule_phase(readings)
        assert phase == "升温扩张"
        assert any("S=" in r for r in reasons)
