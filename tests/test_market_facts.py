"""涨跌幅制度与连板标注 —— `market_facts` 公开 / 制度 helper。"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestLimitUpDetection:
    """`ret >= 9.8` 统一判涨停是错的：创业板/科创板 20cm、北交所 30cm、ST 5cm"""

    def test_board_and_limit_pct(self):
        """ST **不能**一刀切成 5%：创业板/科创板风险警示股仍是 20%"""
        from duanxian.market_facts import board_of, limit_pct

        assert board_of("600000", "浦发银行") == "10cm" and limit_pct("600000", "浦发银行") == 10.0
        assert board_of("300214", "日科化学") == "20cm" and limit_pct("300214", "日科化学") == 20.0
        assert board_of("688981", "中芯国际") == "20cm"
        assert board_of("830799", "艾融软件") == "北交所" and limit_pct("830799", "艾融软件") == 30.0
        assert board_of("920222", "益坤电气") == "北交所" and limit_pct("920222", "益坤电气") == 30.0
        assert board_of("600209", "ST罗顿") == "主板ST" and limit_pct("600209", "ST罗顿") == 5.0
        assert limit_pct("300100", "ST双流") == 20.0, "创业板 ST 是 20% 不是 5%"

    def test_limit_up_prefers_actual_limit_price(self):
        """判涨停优先用「现价 == 涨停价」—— 数据源给的事实，自动适配任何制度变化。"""
        from duanxian import data as bk

        # 益坤电气：涨 10.49% 但涨停价 37.18、现价 31.60 → 没涨停
        assert bk.is_limit_up({"code": "920222", "name": "益坤电气", "ret": 10.49,
                                "close": 31.60, "limit_price": 37.18}) is False
        # 真涨停：现价==涨停价
        assert bk.is_limit_up({"code": "600000", "name": "浦发", "ret": 10.0,
                                "close": 12.31, "limit_price": 12.31}) is True

    def test_falls_back_to_rule_when_price_missing(self):
        """老缓存没有价格字段时退回制度推定，但不能假装能判。"""
        from duanxian import data as bk

        assert bk.is_limit_up({"code": "300214", "name": "日科化学", "ret": 15.59}) is False
        assert bk.is_limit_up({"code": "600000", "name": "浦发", "ret": 9.98}) is True
        assert bk.is_limit_up({"code": "600000", "name": "浦发"}) is None   # 连 ret 都没有


@pytest.mark.unit
class TestBoardLabel:
    """连板标注：反包票要写「N天M板」，不能被东财连板数=1 抹成「1板」。

    欢瑞世纪 2026-07-31 就是实例：东财「连板数」给 1（断板后重新涨停），
    「涨停统计」给 "3/2"。只写「1板」会把题材回流反包的结构完全隐藏。
    """

    def test_fanbao_uses_zt_stat(self):
        from duanxian.market_facts import board_label

        assert board_label(1, "3/2") == "3天2板"
        assert board_label(1, "4/2") == "4天2板"

    def test_normal_consec_uses_boards(self):
        from duanxian.market_facts import board_label

        assert board_label(3, "3/3") == "3板"
        assert board_label(9, "9/9") == "9板"
        assert board_label(2, None) == "2板"
        assert board_label(1, "") == "1板"

    def test_garbage_stat_falls_back(self):
        from duanxian.market_facts import board_label, stat_boards

        assert board_label(2, "乱码") == "2板"
        assert stat_boards("3/2") == 2
        assert stat_boards(None) == 0

    def test_docs_dont_claim_intraday_cannot_compute(self):
        """README 不许再说「盘中算不了、等收盘再跑」——那是改之前的行为。

        文档漂移只体现在一句话里，任何计算测试都抓不到；而看文档的人会照着
        错的说明放弃翻历史复盘。
        """
        import pathlib

        readme = pathlib.Path("README.md").read_text(encoding="utf-8")
        for stale in ("收盘后再跑", "要用当天的收盘价"):
            assert stale not in readme, f"README 还留着过时说法「{stale}」"
        assert "历史场次随时能看" in readme and "定稿记录" in readme, \
            "要写清历史场次能看、以及靠的是定稿记录"

    def test_live_gate_message_scopes_itself_to_live_quotes(self):
        """那个判据的拒绝理由不能读成「整块不可用」。"""
        from duanxian import trade_calendar as tc

        doc = tc.live_quotes_are_close_of.__doc__ or ""
        assert "定稿记录" in doc, "docstring 要点明还有定稿这条路，别被当成总闸"

    def test_no_settled_record_falls_back_to_the_live_gate(self, monkeypatch):
        """定稿记录取不到时仍走原来的实时路径（含它的拒绝理由），不静默出错。"""
        from duanxian import data, emotion_metrics as em, trade_calendar as tc

        monkeypatch.setattr(data, "fetch_prev_pool", lambda d: None)
        monkeypatch.setattr(tc, "live_quotes_are_close_of", lambda d: (False, "轮到实时那条路了"))
        monkeypatch.setattr(tc, "prev_trade_date", lambda d: "2026-07-28")

        r = em.money_effect("2026-07-29")
        assert r["available"] is False and r["reason"] == "轮到实时那条路了"


@pytest.mark.unit
class TestLimitDownIsRegimeAware:
    """跌停要按**这只票自己的涨跌幅制度**判，不能一刀 -9.8%。

    「跌停」这一档在界面上是"今天最惨的那批"。一刀 -9.8% 会把 20cm 的票跌 12%
    也算成跌停 —— 数字看着合理（跌得确实惨），但它没跌停，算进去就夸大了退潮程度。
    涨的那一侧本来就是制度感知的（`is_limit_up` 优先比对涨停价），跌的一侧照做。
    """

    @staticmethod
    def _row(code, name, ret):
        return {"code": code, "name": name, "ret": ret, "prev_boards": 1}

    def test_20cm_falling_12_is_not_limit_down(self):
        from duanxian.market_facts import _is_limit_down

        assert not _is_limit_down(self._row("300001", "某创业板", -12.0)), \
            "20cm 的票跌 12% 不是跌停"

    def test_20cm_falling_20_is_limit_down(self):
        from duanxian.market_facts import _is_limit_down

        assert _is_limit_down(self._row("300001", "某创业板", -19.98))

    def test_10cm_falling_10_is_limit_down(self):
        from duanxian.market_facts import _is_limit_down

        assert _is_limit_down(self._row("600000", "某主板", -10.0))

    def test_10cm_falling_9_is_not(self):
        from duanxian.market_facts import _is_limit_down

        assert not _is_limit_down(self._row("600000", "某主板", -9.0))

    def test_st_falling_5_is_limit_down(self):
        """ST 主板的跌停是 5% —— 一刀 -9.8% 会把它**漏掉**（反方向的错）。"""
        from duanxian.market_facts import _is_limit_down

        assert _is_limit_down(self._row("600001", "ST某某", -5.0))

    def test_missing_ret_is_not_limit_down(self):
        from duanxian.market_facts import _is_limit_down

        assert not _is_limit_down({"code": "600000", "name": "某主板", "ret": None})
