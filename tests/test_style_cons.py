"""短线风格指数成分股：来源分类 + 点开取数（网络全 mock）。"""

from __future__ import annotations

import pandas as pd
import pytest

from duanxian import style_cons


@pytest.fixture(autouse=True)
def _reset_cons_cache():
    style_cons._reset_runtime_state()
    yield
    style_cons._reset_runtime_state()


def test_classify_sources():
    bk = style_cons.classify("yzt", code="BK0815", group="board")
    assert bk["cons_available"] is True
    assert bk["cons_source"] == "em_bk"
    assert "每日重做" in (bk.get("cons_note") or "")

    csi = style_cons.classify("hs300", code="000300", group="benchmark")
    assert csi["cons_source"] == "csindex"
    assert csi["cons_note"] is None

    cni = style_cons.classify("csi2000", code="399303", group="size")
    assert cni["cons_source"] == "cnindex"

    bj = style_cons.classify("bj50", code="899050", group="benchmark")
    assert bj["cons_source"] == "csindex"

    hsi = style_cons.describe("hsi")
    assert hsi["cons_available"] is False
    assert "恒生" in (hsi.get("cons_reason") or "")

    a50 = style_cons.describe("a50")
    assert a50["cons_available"] is False
    assert "期指" in (a50.get("cons_reason") or "")

    unavail = style_cons.describe("ths_emotion")
    assert unavail["cons_available"] is False
    assert unavail["name"] == "同花顺情绪指数"


def test_fetch_unavailable_does_not_network(monkeypatch: pytest.MonkeyPatch):
    def boom(*_a, **_k):
        raise AssertionError("不应联网")

    monkeypatch.setattr("duanxian.fetchers._clist", boom)
    monkeypatch.setattr(style_cons, "_download", boom)
    out = style_cons.fetch("hsi")
    assert out["available"] is False
    assert out["stocks"] == []
    assert out["reason"]


def test_fetch_em_bk(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "duanxian.fetchers._clist",
        lambda *_a, **_k: [
            {"f12": "600519", "f14": "贵州茅台", "f3": 1.2},
            {"f12": "000001", "f14": "平安银行", "f3": -0.5},
        ],
    )
    out = style_cons.fetch("yzt")
    assert out["available"] is True
    assert out["source"] == "em_bk"
    assert out["count"] == 2
    assert out["stocks"][0]["code"] == "600519"
    assert out["stocks"][0]["market"] == "SH"
    assert out["stocks"][1]["market"] == "SZ"


def test_fetch_csindex_jpeg_explains(monkeypatch: pytest.MonkeyPatch):
    class Resp:
        status_code = 200
        content = b"\xff\xd8\xff" + b"x" * 20
        headers = {"Content-Type": "image/jpeg"}

    monkeypatch.setattr("duanxian.fetchers._direct_get", lambda *_a, **_k: Resp())
    out = style_cons.fetch("hs300")
    assert out["available"] is False
    assert "图片" in (out.get("reason") or "")
    assert out["stocks"] == []


def test_frame_to_stocks_from_csindex_columns():
    df = pd.DataFrame({
        "日期": ["2026-09-18", "2026-09-18"],
        "成分券代码": ["600519", "1"],
        "成分券名称": ["贵州茅台", "平安银行"],
    })
    stocks = style_cons._frame_to_stocks(df)
    assert [s["code"] for s in stocks] == ["600519", "000001"]
    assert stocks[0]["name"] == "贵州茅台"


def test_frame_to_stocks_skips_csindex_index_code_column():
    df = pd.DataFrame({
        "日期Date": ["20260918", "20260918"],
        "指数代码 Index Code": ["000905", "000905"],
        "指数名称 Index Name": ["中证500", "中证500"],
        "成份券代码Constituent Code": ["000009", "000012"],
        "成份券名称Constituent Name": ["中国宝安", "南玻A"],
    })
    stocks = style_cons._frame_to_stocks(df)
    assert [s["code"] for s in stocks] == ["000009", "000012"]
    assert [s["name"] for s in stocks] == ["中国宝安", "南玻A"]


def test_public_cons_usable_rejects_csindex_singleton():
    assert style_cons.public_cons_usable({
        "available": True,
        "source": "csindex",
        "code": "000905",
        "stocks": [{"code": "000905", "name": "中证500"}],
    }) is False
    assert style_cons.public_cons_usable({
        "available": True,
        "source": "em_bk",
        "code": "BK0815",
        "stocks": [{"code": "600519", "name": "贵州茅台"}, {"code": "000001", "name": "平安银行"}],
    }) is True


def test_latest_date_frame_keeps_newest():
    df = pd.DataFrame({
        "日期": ["2026-01-01", "2026-09-18", "2026-09-18"],
        "样本代码": ["000001", "000002", "000003"],
        "样本简称": ["旧", "新1", "新2"],
    })
    latest = style_cons._latest_date_frame(df)
    assert list(latest["样本代码"]) == ["000002", "000003"]
