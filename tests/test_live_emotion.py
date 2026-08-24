"""打板情绪 —— `live_emotion.snapshot` 缓存与按日归档。"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestLiveEmotionCache:
    """今日实时打板情绪的缓存语义。

    取一次要打四个池 + 两次交易日历，实测冷态 8.8 秒，而界面 5 秒一刷 ——
    不缓存就会请求叠着堆（日志里能看到并发好几条），又拖页面又撞限流。
    """

    @pytest.fixture(autouse=True)
    def _clear(self):
        from duanxian import live_emotion as le

        le._cache.clear()
        yield
        le._cache.clear()

    def test_empty_but_valid_result_is_cached(self):
        """🔴 判据必须是 `is not None`。

        写成 `if val:` 会把**合法的空结果**当失败：今天跌停 0 家时池子是 `[]`，
        用真值判断就永不入缓存、每次重打网络（实测热态因此卡在 1.78 秒 = 没缓存）。
        """
        from duanxian import live_emotion as le

        calls = []
        build = lambda: calls.append(1) or []      # noqa: E731  合法的"今天没有"
        assert le._cached("k", 60, build) == []
        assert le._cached("k", 60, build) == []
        assert len(calls) == 1, "空但有效的结果没进缓存，会每次重打网络"

    def test_failure_is_not_cached(self):
        """取数失败（None）不许缓存 —— 否则一次抖动锁住一整个 TTL。"""
        from duanxian import live_emotion as le

        calls = []
        build = lambda: calls.append(1) or None    # noqa: E731
        le._cached("k", 60, build)
        le._cached("k", 60, build)
        assert len(calls) == 2, "失败被缓存了"

    def test_ttl_expiry_refetches(self):
        from duanxian import live_emotion as le

        calls = []
        build = lambda: calls.append(1) or ["x"]   # noqa: E731
        le._cached("k", 0.0, build)
        le._cached("k", 0.0, build)
        assert len(calls) == 2

    def test_calendar_lookups_are_cached_too(self):
        """`resolve_as_of` / `is_settled` 每次都可能打网络 ——
        只缓存池子的话热态还是 3.9 秒，跟 5 秒间隔差不多，等于没修。"""
        import inspect

        from duanxian import live_emotion as le

        src = inspect.getsource(le.snapshot)
        i = src.index("resolve_as_of")
        assert "_cached" in src[max(0, i - 200):i + 80], "resolve_as_of 没走缓存"
        i = src.index("is_settled")
        assert "_cached" in src[max(0, i - 200):i], "is_settled 没走缓存"


@pytest.mark.unit
class TestLiveEmotionArchive:
    """实时打板情绪按日归档：盘中覆盖写，次日作「昨日」对照（含晋级率）。"""

    @pytest.fixture(autouse=True)
    def _iso(self, tmp_path, monkeypatch):
        from duanxian import live_emotion as le

        le._cache.clear()
        monkeypatch.setattr(le, "_CACHE_DIR", str(tmp_path))
        yield
        le._cache.clear()

    def test_save_and_load_includes_promotion_rate(self, tmp_path):
        from duanxian import live_emotion as le

        le._save_archive("2026-08-19", {
            "zt_count": 36, "dt_count": 2, "zb_count": 10,
            "max_boards": 5, "lianban_count": 8,
            "seal_rate": 0.78, "break_rate": 0.22,
            "promotion_rate": 0.15, "promotion_base": 40,
        })
        y = le._yesterday_slice("2026-08-19")
        assert y["zt_count"] == 36
        assert y["promotion_rate"] == 0.15
        assert y["promotion_base"] == 40
        assert (tmp_path / "2026-08-19.json").is_file()

    def test_missing_archive_returns_empty(self):
        from duanxian import live_emotion as le

        assert le._yesterday_slice("2099-01-01") == {}
        assert le._yesterday_slice(None) == {}

    def test_snapshot_attaches_yesterday_from_archive(self, monkeypatch):
        from duanxian import live_emotion as le

        le._save_archive("2026-08-19", {
            "zt_count": 36, "promotion_rate": 0.25, "seal_rate": 0.8,
        })
        monkeypatch.setattr(le, "china_now", lambda: __import__("datetime").datetime(2026, 8, 20, 15, 30))
        monkeypatch.setattr(
            "duanxian.trade_calendar.prev_trade_date", lambda d: "2026-08-19")
        monkeypatch.setattr(
            "duanxian.trade_calendar.is_settled", lambda d: False)
        monkeypatch.setattr(
            "duanxian.trade_calendar.quote_trade_day", lambda: "2026-08-20")
        monkeypatch.setattr(
            "duanxian.trade_calendar.latest_session", lambda: "2026-08-19")

        def fake_pool(kind, ymd):
            if kind == "getTopicZTPool" and ymd == "20260820":
                return [{"c": "000001", "lbc": 2}, {"c": "000002", "lbc": 1}]
            if kind == "getTopicZTPool" and ymd == "20260819":
                return [{"c": "000001"}, {"c": "000003"}]
            if kind == "getTopicZBPool":
                return [{"c": "000009"}]
            if kind == "getTopicDTPool":
                return []
            return []

        monkeypatch.setattr(le, "_pool", fake_pool)
        snap = le.snapshot()
        assert snap["available"] is True
        assert snap["prev_date"] == "2026-08-19"
        assert snap["yesterday"]["zt_count"] == 36
        assert snap["yesterday"]["promotion_rate"] == 0.25
        assert snap["promotion_rate"] == 0.5
        assert snap["promotion_base"] == 2
        # 今日快照已落盘，供明天对照
        assert le._load_archive("2026-08-20").get("zt_count") == 2

    def test_weekend_shows_friday_vs_thursday_without_saturday_archive(
            self, tmp_path, monkeypatch):
        """周六仍展示周五 vs 周四，且不得把周五数据写成周六.json。

        🔴 东财周末请求「今天」常仍返回上一场非空涨停池 —— 绝不能因此当成 live。
        """
        from duanxian import live_emotion as le

        le._save_archive("2026-08-20", {  # 周四
            "zt_count": 40, "seal_rate": 0.7, "promotion_rate": 0.2,
        })
        monkeypatch.setattr(
            le, "china_now",
            lambda: __import__("datetime").datetime(2026, 8, 22, 12, 30))  # 周六
        monkeypatch.setattr(
            "duanxian.trade_calendar.quote_trade_day", lambda: "2026-08-21")
        monkeypatch.setattr(
            "duanxian.trade_calendar.latest_session", lambda: "2026-08-21")
        monkeypatch.setattr(
            "duanxian.trade_calendar.prev_trade_date",
            lambda d: {"2026-08-22": "2026-08-21", "2026-08-21": "2026-08-20"}.get(d))
        monkeypatch.setattr(
            "duanxian.trade_calendar.is_settled", lambda d: d == "2026-08-21")

        def fake_pool(kind, ymd):
            # 周末请求周六仍非空（东财假今日）—— 若误信会得到 22 vs 21 同数对照
            if ymd == "20260822":
                return [{"c": "000001", "lbc": 3}, {"c": "000002", "lbc": 1}]
            if kind == "getTopicZTPool" and ymd == "20260821":
                return [{"c": "000001", "lbc": 3}, {"c": "000002", "lbc": 1}]
            if kind == "getTopicZTPool" and ymd == "20260820":
                return [{"c": "000001"}, {"c": "000003"}, {"c": "000004"}]
            if kind == "getTopicZBPool" and ymd == "20260821":
                return [{"c": "000009"}]
            if kind == "getTopicDTPool":
                return []
            return []

        monkeypatch.setattr(le, "_pool", fake_pool)
        snap = le.snapshot()
        assert snap["available"] is True
        assert snap["date"] == "2026-08-21"
        assert snap["prev_date"] == "2026-08-20"
        assert snap["is_live"] is False
        assert snap["phase"] == "非交易日"
        assert snap["zt_count"] == 2
        assert snap["yesterday"]["zt_count"] == 40
        assert not (tmp_path / "2026-08-22.json").exists()
        assert not (tmp_path / "2026-08-21.json").exists()  # 非 live 不覆盖写

    def test_snapshot_as_of_overrides_calendar(self, monkeypatch):
        """传入 as_of 时按指定场次取池，不跟日历今天走。"""
        from duanxian import live_emotion as le

        monkeypatch.setattr(
            le, "china_now",
            lambda: __import__("datetime").datetime(2026, 8, 20, 10, 30))
        monkeypatch.setattr(
            "duanxian.trade_calendar.prev_trade_date",
            lambda d: "2026-08-18" if d == "2026-08-19" else None)
        monkeypatch.setattr(
            "duanxian.trade_calendar.is_settled", lambda d: True)
        monkeypatch.setattr(
            "duanxian.trade_calendar.quote_trade_day", lambda: "2026-08-20")
        monkeypatch.setattr(
            "duanxian.trade_calendar.latest_session", lambda: "2026-08-19")
        monkeypatch.setattr(
            "duanxian.trade_calendar.should_write_daily_cache", lambda d: False)

        def fake_pool(kind, ymd):
            if kind == "getTopicZTPool" and ymd == "20260819":
                return [{"c": "000001", "lbc": 3}]
            if kind == "getTopicZTPool" and ymd == "20260818":
                return [{"c": "000001"}, {"c": "000002"}]
            if kind == "getTopicZTPool" and ymd == "20260820":
                return [{"c": "999999", "lbc": 1}]
            if kind == "getTopicZBPool":
                return []
            if kind == "getTopicDTPool":
                return []
            return []

        monkeypatch.setattr(le, "_pool", fake_pool)
        snap = le.snapshot(as_of="2026-08-19")
        assert snap["available"] is True
        assert snap["date"] == "2026-08-19"
        assert snap["is_live"] is False
        assert snap["zt_count"] == 1
        assert snap["promotion_rate"] == 0.5
        assert snap["max_boards"] == 3
