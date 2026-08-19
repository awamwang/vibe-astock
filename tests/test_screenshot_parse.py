"""券商持仓截图解析：规范化与写入校验（不调真实模型）。"""

from __future__ import annotations

import pytest

from duanxian import screenshot_parse as sp


class TestNormalizeParsed:
    def test_full_broker_like_payload(self):
        raw = {
            "broker": "中金财富",
            "equity": "136,140.15",
            "available": 3404.15,
            "withdrawable": 440.85,
            "frozen": 0,
            "stock_market_value": 132736,
            "position_pnl": -12797.25,
            "daily_pnl": -4698.75,
            "daily_pnl_pct": -3.34,
            "note": None,
            "holdings": [
                {
                    "code": "603629", "name": "利通电子", "shares": 200,
                    "available_shares": 200, "cost": 130.031, "price": 134.64,
                    "pnl": 921.8, "market_value": 26928,
                },
                {
                    "code": 301085, "name": "亚康股份", "shares": 1600,
                    "available_shares": 1600, "cost": 66.021, "price": 66.13,
                    "pnl": 174.4, "market_value": 105808,
                },
                {
                    "code": "300243", "name": "瑞丰高材", "shares": 0,
                    "cost": None, "price": 18.74, "pnl": None, "market_value": None,
                },
            ],
        }
        out = sp.normalize_parsed(raw)
        assert out["broker"] == "中金财富"
        assert out["equity"] == 136140.15
        assert out["daily_pnl_pct"] == -3.34
        assert len(out["holdings"]) == 3
        h0 = out["holdings"][0]
        assert h0["code"] == "603629" and h0["include"] is True
        h2 = out["holdings"][2]
        assert h2["shares"] == 0 and h2["include"] is False

    def test_json_fence_and_pad_code(self):
        text = '```json\n{"equity": 1, "holdings": [{"code": "123", "shares": 100, "cost": 10}]}\n```'
        out = sp.normalize_parsed(text)
        assert out["holdings"][0]["code"] == "000123"
        assert out["holdings"][0]["include"] is True

    def test_duplicate_codes_keep_first(self):
        out = sp.normalize_parsed({
            "holdings": [
                {"code": "600000", "shares": 100, "cost": 10},
                {"code": "600000", "shares": 200, "cost": 11},
            ],
        })
        assert len(out["holdings"]) == 1
        assert out["holdings"][0]["shares"] == 100


class TestValidateApply:
    def test_filters_unchecked_and_zero(self):
        eq, note, hs, replace = sp.validate_apply_payload({
            "equity": 1000,
            "note": "x",
            "replace": True,
            "holdings": [
                {"code": "603629", "shares": 200, "cost": 130, "include": True},
                {"code": "300243", "shares": 0, "cost": 1, "include": True},
                {"code": "301085", "shares": 1600, "cost": 66, "include": False},
            ],
        })
        assert eq == 1000
        assert note == "x"
        assert replace is True
        assert hs == [{"code": "603629", "shares": 200.0, "cost": 130.0}]

    def test_reject_negative_equity(self):
        with pytest.raises(ValueError, match="负"):
            sp.validate_apply_payload({"equity": -1, "holdings": []})


class TestStripDataUrl:
    def test_plain_b64(self):
        mime, raw = sp._strip_data_url("aaaa")
        assert mime == "image/png"
        assert raw == "aaaa"

    def test_data_uri(self):
        mime, raw = sp._strip_data_url("data:image/jpeg;base64,qqq")
        assert mime == "image/jpeg"
        assert raw == "qqq"
