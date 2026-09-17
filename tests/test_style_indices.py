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
