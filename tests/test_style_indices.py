"""短线风格指数：分组装配纯逻辑（不打网络）。"""

from __future__ import annotations

import pytest

from duanxian.style_indices import (
    GROUPS,
    ITEMS,
    UNAVAILABLE,
    assemble,
    snapshot,
)


def _q(pct, price=10.0, up=None, down=None):
    return {"change_pct": pct, "price": price, "up": up, "down": down, "code": "x"}


@pytest.mark.unit
class TestCatalog:
    def test_keys_unique(self):
        keys = [i.key for i in ITEMS]
        assert len(keys) == len(set(keys))
        assert {i.group for i in ITEMS} == {g for g, _ in GROUPS}

    def test_user_aliases_mapped(self):
        by_key = {i.key: i for i in ITEMS}
        assert by_key["yzt_yz"].code == "BK1050"
        assert by_key["ylb_yz"].code == "BK1051"
        assert by_key["small"].code == "BK1643"
        assert by_key["large"].code == "BK1663"
        assert by_key["micro"].code == "BK1158"
        assert by_key["csi2000"].code == "399303"
        assert by_key["ylb2plus"].code == "BK1645"
        assert by_key["yzt_first"].code == "BK1630"
        assert by_key["high_100d"].code == "BK1676"
        assert by_key["subnew"].code == "BK0501"
        assert by_key["st"].code == "BK0511"
        assert by_key["micro_sel"].code == "BK1644"
        item_names = {i.name for i in ITEMS}
        assert "破净股" not in item_names
        assert "红利股" not in item_names
        assert "低市净率" not in item_names
        assert "股权激励" not in item_names
        names = {x["name"] for x in UNAVAILABLE}
        assert "同花顺情绪指数" in names
        assert "A股平均股价" in names
        assert "短期期货恐慌指数" in names
        assert "高贝塔值" in names


@pytest.mark.unit
class TestAssemble:
    def test_groups_keep_catalog_order_and_nulls(self):
        quotes = {
            "yzt_yz": _q(0.11, up=36, down=54),
            "small": _q(-0.37),
            "sh": _q(-0.41, price=3875.6),
        }
        out = assemble(quotes)
        assert out["available"] is True
        assert out["hit"] == 3
        assert out["total"] == len(ITEMS)
        board = next(g for g in out["groups"] if g["id"] == "board")
        assert board["items"][0]["key"] == "yzt_yz"
        assert board["items"][0]["change_pct"] == 0.11
        assert board["items"][0]["up"] == 36
        yzt = next(x for x in board["items"] if x["key"] == "yzt")
        assert yzt["available"] is False
        assert yzt["change_pct"] is None
        size = next(g for g in out["groups"] if g["id"] == "size")
        assert any(x["key"] == "small" and x["change_pct"] == -0.37 for x in size["items"])
        assert any(x["name"] == "同花顺情绪指数" for x in out["unavailable"])

    def test_zero_is_available(self):
        out = assemble({"sh": _q(0.0)})
        sh = next(x for g in out["groups"] for x in g["items"] if x["key"] == "sh")
        assert sh["available"] is True
        assert sh["change_pct"] == 0.0

    def test_empty_quotes_not_available(self):
        out = assemble({})
        assert out["available"] is False
        assert out["hit"] == 0
        assert len(out["groups"]) == len(GROUPS)


@pytest.mark.unit
class TestSnapshotCache:
    @pytest.fixture(autouse=True)
    def _iso(self, monkeypatch):
        from duanxian import style_indices as si

        si._reset_runtime_state()
        monkeypatch.setattr(si, "_load_quotes", lambda: {"sh": _q(-0.41)})
        monkeypatch.setattr(
            si.trade_calendar, "resolve_as_of",
            lambda _t=None: ("2026-09-17", "2026-09-16", True),
        )
        monkeypatch.setattr(si.trade_calendar, "is_settled", lambda _d: False)
        yield
        si._reset_runtime_state()

    def test_snapshot_attaches_session(self):
        out = snapshot()
        assert out["date"] == "2026-09-17"
        assert out["is_live"] is True
        assert out["available"] is True
        sh = next(x for g in out["groups"] for x in g["items"] if x["key"] == "sh")
        assert sh["change_pct"] == -0.41

    def test_second_call_does_not_refetch(self, monkeypatch):
        from duanxian import style_indices as si

        calls = {"n": 0}

        def once():
            calls["n"] += 1
            return {"sh": _q(-0.41)}

        monkeypatch.setattr(si, "_load_quotes", once)
        si._reset_runtime_state()
        a = snapshot()
        b = snapshot()
        assert calls["n"] == 1
        assert a["hit"] == b["hit"] == 1


@pytest.mark.unit
class TestHttpAndFrontend:
    def test_get_returns_snapshot(self, monkeypatch):
        from fastapi.testclient import TestClient

        import server
        from duanxian import style_indices as si

        fake = assemble({"yzt_yz": _q(0.11)})
        fake["date"] = "2026-09-17"
        fake["is_live"] = True
        monkeypatch.setattr(server.style_indices, "snapshot", lambda: fake)
        monkeypatch.setattr(si, "snapshot", lambda: fake)
        r = TestClient(server.app).get("/api/market/style-indices")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        board = next(g for g in body["groups"] if g["id"] == "board")
        assert board["items"][0]["name"] == "昨日涨停表现"
        pref = body["preference"]
        assert pref["status"] == "partial"
        assert pref["hotspots"] == []
        assert pref["board_group"]["vs"] == "不足"

    def test_sidebar_and_route(self):
        import pathlib

        layout = pathlib.Path("frontend/src/components/layout/Layout.tsx").read_text(encoding="utf-8")
        router = pathlib.Path("frontend/src/router.tsx").read_text(encoding="utf-8")
        page = pathlib.Path("frontend/src/pages/ShortStyle.tsx").read_text(encoding="utf-8")
        assert '{ to: "/short-style"' in layout
        assert 'label: "短线风格"' in layout
        assert 'path: "/short-style"' in router
        assert "ShortStyle" in router
        assert "fetchStyleIndices" in page
        assert "打板情绪" not in page or "不是打板情绪" in page
        assert "unavailable" in page
        assert "风格热点" in page
        assert "大小盘价差" in page
        assert "组内领涨" in page
        assert "价升面窄" in page
        assert "价跌面宽" in page
        assert "国证2000" in page
        assert "沪深300" in page
        assert "超额 = 当场涨幅 − 中证全指" in page
        assert "东财小盘" in page
        assert "不是赚钱效应" in page
        assert "不是风格轮动" in page
        assert "短线情绪" not in page
        assert "市场情绪" not in page
        assert "情绪共振" not in page
        assert "主线龙头" not in page
        resonance = pathlib.Path("frontend/src/pages/ShortResonance.tsx").read_text(encoding="utf-8")
        assert "风格偏好" not in resonance
        assert "风格热点" not in resonance
        assert "大小盘价差" not in resonance
        assert "AskAiButton" in page
        assert "风格热点是哪些" in page
        assert "大小盘价差怎么读" in page
        assert "打板风格组和中证全指是否同向" in page
        assert "风格热点：" in page
        assert "大小盘价差（东财小盘 − 大盘）" in page
        assert "打板风格组相对中证全指" in page
        assert "change_pct -" not in page
        assert "small - large" not in page
        server_src = pathlib.Path("server.py").read_text(encoding="utf-8")
        assert server_src.count('@app.get("/api/market/style-indices")') == 1
        assert "/api/market/style-preference" not in server_src
        assert "style-preference" not in router
        for rel in (
            "duanxian/trade_budget.py",
            "duanxian/risk_stance.py",
            "duanxian/sentiment_score.py",
            "frontend/src/pages/TradeBudgetPage.tsx",
        ):
            text = pathlib.Path(rel).read_text(encoding="utf-8")
            assert "风格偏好" not in text
            assert "风格热点" not in text
            assert "大小盘价差" not in text


@pytest.mark.unit
class TestPreference:
    def test_empty_is_absent(self):
        out = assemble({})
        pref = out["preference"]
        assert pref["status"] == "absent"
        assert pref["hotspots"] == []
        assert pref["group_leads"] == []
        assert pref["size_spread"] == {"value": None, "status": "不足"}
        assert pref["size_spread_cnindex"] == {"value": None}
        assert pref["board_group"]["vs"] == "不足"
        assert pref["board_group"]["mean"] is None

    def test_hotspots_exclude_benchmark_external_and_csi_all(self):
        out = assemble({
            "csi_all": _q(0.0),
            "sh": _q(9.0),
            "hsi": _q(8.0),
            "a50": _q(7.0),
            "small": _q(1.0),
        })
        keys = [h["key"] for h in out["preference"]["hotspots"]]
        assert "sh" not in keys
        assert "hsi" not in keys
        assert "a50" not in keys
        assert "csi_all" not in keys
        assert keys == ["small"]

    def test_top5_then_width_filter_does_not_backfill(self):
        out = assemble({
            "csi_all": _q(0.0),
            "yzt_yz": _q(5.0, up=80, down=20),
            "yzt": _q(4.0, up=80, down=20),
            "ylb_yz": _q(3.0, up=80, down=20),
            "ylb": _q(2.0, up=80, down=20),
            "yzb": _q(1.0, up=10, down=90),
            "new_high": _q(0.9, up=80, down=20),
        })
        keys = [h["key"] for h in out["preference"]["hotspots"]]
        assert keys == ["yzt_yz", "yzt", "ylb_yz", "ylb"]
        assert "yzb" not in keys
        assert "new_high" not in keys
        assert len(keys) == 4

    def test_board_group_mean_excludes_high_turnover(self):
        quotes = {
            "csi_all": _q(0.5),
            "yzt_yz": _q(1.0),
            "yzt": _q(1.0),
            "ylb_yz": _q(1.0),
            "ylb": _q(1.0),
            "yzb": _q(1.0),
            "ylb2plus": _q(1.0),
            "yzt_first": _q(1.0),
            "y_high_to": _q(100.0),
            "y_high_amp": _q(50.0),
            "yzt_touch": _q(40.0),
        }
        pref = assemble(quotes)["preference"]
        assert pref["board_group"]["n_valid"] == 7
        assert pref["board_group"]["mean"] == pytest.approx(1.0)
        assert pref["board_group"]["vs"] == "同向"

    def test_board_group_three_valid_is_insufficient(self):
        pref = assemble({
            "csi_all": _q(1.0),
            "yzt_yz": _q(1.0),
            "yzt": _q(1.0),
            "ylb_yz": _q(1.0),
        })["preference"]
        assert pref["board_group"]["n_valid"] == 3
        assert pref["board_group"]["mean"] is None
        assert pref["board_group"]["vs"] == "不足"

    def test_near_flat_when_mean_or_csi_abs_below_0_1(self):
        a = assemble({
            "csi_all": _q(1.0),
            "yzt_yz": _q(0.05),
            "yzt": _q(0.05),
            "ylb_yz": _q(0.05),
            "ylb": _q(0.05),
        })["preference"]
        assert a["board_group"]["vs"] == "近平"
        b = assemble({
            "csi_all": _q(0.05),
            "yzt_yz": _q(1.0),
            "yzt": _q(1.0),
            "ylb_yz": _q(1.0),
            "ylb": _q(1.0),
        })["preference"]
        assert b["board_group"]["vs"] == "近平"

    def test_board_group_opposite_sign(self):
        pref = assemble({
            "csi_all": _q(-0.5),
            "yzt_yz": _q(1.0),
            "yzt": _q(1.0),
            "ylb_yz": _q(1.0),
            "ylb": _q(1.0),
        })["preference"]
        assert pref["board_group"]["vs"] == "反向"

    def test_missing_csi_all_partial_keeps_spread_and_leads(self):
        out = assemble({
            "small": _q(1.2),
            "large": _q(0.4),
            "yzt_yz": _q(0.8),
            "mid": _q(0.1),
            "sh": _q(9.0),
        })
        pref = out["preference"]
        assert pref["status"] == "partial"
        assert pref["hotspots"] == []
        assert pref["board_group"]["vs"] == "不足"
        assert pref["size_spread"]["status"] == "ok"
        assert pref["size_spread"]["value"] == pytest.approx(0.8)
        lead_keys = {x["key"] for x in pref["group_leads"]}
        assert "yzt_yz" in lead_keys
        assert "small" in lead_keys
        assert "sh" in lead_keys

    def test_missing_small_size_spread_insufficient(self):
        pref = assemble({
            "csi_all": _q(0.2),
            "large": _q(0.4),
            "micro": _q(3.0),
        })["preference"]
        assert pref["size_spread"] == {"value": None, "status": "不足"}
        assert pref["hotspots"][0]["key"] == "micro"

    def test_micro_does_not_rewrite_size_spread(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "small": _q(1.0),
            "large": _q(0.2),
            "micro": _q(9.0),
        })["preference"]
        assert pref["size_spread"]["status"] == "ok"
        assert pref["size_spread"]["value"] == pytest.approx(0.8)

    def test_cnindex_spread_is_separate(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "small": _q(1.0),
            "large": _q(0.2),
            "csi2000": _q(0.7),
            "hs300": _q(0.1),
        })["preference"]
        assert pref["size_spread"]["value"] == pytest.approx(0.8)
        assert pref["size_spread"]["status"] == "ok"
        assert pref["size_spread_cnindex"]["value"] == pytest.approx(0.6)

    def test_cnindex_missing_side_hidden(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "small": _q(1.0),
            "large": _q(0.2),
            "csi2000": _q(0.7),
        })["preference"]
        assert pref["size_spread"]["status"] == "ok"
        assert pref["size_spread_cnindex"]["value"] is None

    def test_excess_tie_uses_catalog_order(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "yzt_yz": _q(1.0),
            "yzt": _q(1.0),
            "ylb_yz": _q(1.0),
            "ylb": _q(1.0),
            "yzt_first": _q(0.5),
            "y_high_to": _q(0.5),
            "new_high": _q(0.2),
        })["preference"]
        keys = [h["key"] for h in pref["hotspots"]]
        assert keys == ["yzt_yz", "yzt", "ylb_yz", "ylb", "yzt_first"]
        assert "y_high_to" not in keys

    def test_width_flag_on_items(self):
        out = assemble({
            "csi_all": _q(0.0),
            "yzt_yz": _q(1.0, up=10, down=90),
            "small": _q(-1.0, up=80, down=20),
            "div_csi": _q(0.5, up=0, down=0),
        })
        by_key = {it["key"]: it for g in out["groups"] for it in g["items"]}
        assert by_key["yzt_yz"]["width_flag"] == "价升面窄"
        assert by_key["small"]["width_flag"] == "价跌面宽"
        assert by_key["div_csi"]["width_flag"] is None

    def test_group_lead_skips_hotspot(self):
        out = assemble({
            "csi_all": _q(0.0),
            "yzt_yz": _q(5.0),
            "yzt": _q(4.0),
            "ylb_yz": _q(3.0),
            "ylb": _q(2.5),
            "small": _q(2.0),
            "mid": _q(1.5),
            "large": _q(0.1),
        })
        pref = out["preference"]
        assert "small" in {h["key"] for h in pref["hotspots"]}
        assert "large" not in {h["key"] for h in pref["hotspots"]}
        size_lead = next((x for x in pref["group_leads"] if x["group"] == "size"), None)
        assert size_lead is None
        assert "mid" not in {x["key"] for x in pref["group_leads"]}

    def test_high_turnover_can_be_hotspot(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "y_high_to": _q(3.0),
            "small": _q(0.2),
        })["preference"]
        assert pref["hotspots"][0]["key"] == "y_high_to"
        assert pref["hotspots"][0]["excess"] == pytest.approx(3.0)

    def test_no_breadth_hotspot_uses_excess_only(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "div_csi": _q(2.0),
            "yzt_yz": _q(1.5, up=10, down=90),
            "small": _q(0.2, up=80, down=20),
        })["preference"]
        keys = [h["key"] for h in pref["hotspots"]]
        assert keys[0] == "div_csi"
        assert pref["hotspots"][0]["excess"] == pytest.approx(2.0)
        assert "yzt_yz" not in keys

    def test_csi2000_can_be_hotspot(self):
        pref = assemble({
            "csi_all": _q(0.0),
            "csi2000": _q(1.2),
            "small": _q(0.1),
        })["preference"]
        assert pref["hotspots"][0]["key"] == "csi2000"
        assert pref["hotspots"][0]["excess"] == pytest.approx(1.2)

