"""板块方言映射与重点板块跟踪。"""

from __future__ import annotations

import json
import os

import pytest


@pytest.mark.unit
class TestBlockDialect:
    def test_resolve_by_name(self):
        from duanxian import block_dialect as bd

        idx = bd.build_kpl_index([
            {"code": "801660", "name": "通信", "power": 6609},
            {"code": "803023", "name": "AI应用", "power": 1974},
        ])
        hit = bd.resolve_to_kpl(name="通信", index=idx)
        assert hit["status"] == "matched"
        assert hit["code"] == "801660"

    def test_resolve_ths_follow(self):
        from duanxian import block_dialect as bd

        idx = bd.build_kpl_index([{"code": "801660", "name": "通信"}])
        hit = bd.resolve_ths_block(
            {"kind": "theme", "id": "ths-1", "name": "通信"},
            idx,
        )
        assert hit["status"] == "matched"
        assert hit["code"] == "801660"
        assert hit["source_id"] == "ths-1"

    def test_unmatched(self):
        from duanxian import block_dialect as bd

        idx = bd.build_kpl_index([{"code": "801660", "name": "通信"}])
        hit = bd.resolve_to_kpl(name="不存在板块", index=idx)
        assert hit["status"] == "unmatched"
        assert hit["code"] == ""


@pytest.mark.unit
class TestMoodBlockPlateParse:
    def test_parse_dated_plate_info(self):
        from duanxian import mood_block as mb

        # 与 apphis GetPlate_Info_QJ 探测一致
        row = mb._parse_plate_info_list(
            [1, 6609, 698458592200, 2546553941, -0.802, 12, 1081979972, 630404388],
            dated=True,
        )
        assert row is not None
        assert row["power"] == 6609
        assert row["pct"] == -0.802
        assert row["m_net"] == 2546553941
        assert row["zt"] == 12

    def test_ranking_archive_reuse(self, tmp_path, monkeypatch):
        from duanxian import mood_block as mb

        monkeypatch.setattr(mb, "_CACHE_DIR", str(tmp_path))
        mb._cache.clear()
        date = "2026-09-11"
        payload = {
            "date": date,
            "available": True,
            "blocks": [
                {"code": "801660", "name": "通信", "power": 6609, "pct": -0.8,
                 "speed": 0.1, "m_net": 1, "zt": 2, "sort": 1},
            ],
            "api_time": 1,
            "from_archive": False,
        }
        path = os.path.join(str(tmp_path), f"{date}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

        called = {"n": 0}

        def boom(*_a, **_k):
            called["n"] += 1
            raise AssertionError("should not hit network")

        monkeypatch.setattr(mb, "_fetch_ranking_pages", boom)
        out = mb.ranking_for_date(date)
        assert out["available"] is True
        assert out["from_archive"] is True
        assert out["blocks"][0]["code"] == "801660"
        assert called["n"] == 0


@pytest.mark.unit
class TestFocusBlocks:
    def test_build_tracked_hot_and_follow(self):
        from duanxian import block_dialect as bd
        from duanxian import focus_blocks as fb

        y_blocks = [
            {"code": "801660", "name": "通信", "power": 6609, "pct": -0.8,
             "m_net": 1, "zt": 2, "sort": 1},
            {"code": "803023", "name": "AI应用", "power": 1974, "pct": -1.0,
             "m_net": 0, "zt": 1, "sort": 2},
        ]
        index = bd.build_kpl_index(y_blocks)
        follows = [
            {"kind": "theme", "id": "x1", "name": "AI应用"},
            {"kind": "theme", "id": "x2", "name": "完全不存在"},
        ]
        items = fb._build_tracked(y_blocks=y_blocks, follows=follows, index=index)
        by_name = {it["name"]: it for it in items}
        assert "通信" in by_name
        assert "hot" in by_name["通信"]["tags"]
        assert "AI应用" in by_name
        assert "follow" in by_name["AI应用"]["tags"]
        assert "hot" not in by_name["AI应用"]["tags"]
        unmatched = [it for it in items if it.get("map_status") == "unmatched"]
        assert len(unmatched) == 1
        assert unmatched[0]["name"] == "完全不存在"

    def test_snapshot_uses_archive_and_plate(self, tmp_path, monkeypatch):
        from duanxian import focus_blocks as fb
        from duanxian import mood_block as mb
        from duanxian import message_follow_blocks as mfb

        monkeypatch.setattr(mb, "_CACHE_DIR", str(tmp_path))
        mb._cache.clear()
        fb._cache.clear()

        monkeypatch.setattr(
            "duanxian.trade_calendar.resolve_as_of",
            lambda: ("2026-09-12", "2026-09-11", False),
        )
        monkeypatch.setattr(
            "duanxian.trade_calendar.is_calendar_session_live",
            lambda: False,
        )
        monkeypatch.setattr(mfb, "load_blocks", lambda: [
            {"kind": "theme", "id": "1", "name": "通信"},
        ])

        y_blocks = [
            {"code": "801660", "name": "通信", "power": 6609, "pct": -0.8,
             "speed": 0.1, "m_net": 100, "zt": 2, "sort": 1},
        ]
        t_blocks = [
            {"code": "801660", "name": "通信", "power": 500, "pct": 1.2,
             "speed": 0.2, "m_net": 50, "zt": 1, "sort": 3},
        ]

        def fake_rank(date, **_kw):
            if date == "2026-09-11":
                return {
                    "date": date,
                    "available": True,
                    "blocks": y_blocks,
                    "from_archive": True,
                    "api_time": 1,
                    "reason": None,
                }
            return {
                "date": date,
                "available": True,
                "blocks": t_blocks,
                "from_archive": True,
                "api_time": 2,
                "reason": None,
            }

        monkeypatch.setattr(mb, "ranking_for_date", fake_rank)
        monkeypatch.setattr(mb, "fetch_ranking_catalog", lambda **_k: [])

        def fake_plate(code, *, date=None):
            if date == "2026-09-12" or date is None:
                return {
                    "code": code, "date": "2026-09-12",
                    "power": 500, "pct": 1.2, "m_net": 50, "amount": 1, "zt": 1, "sort": 3,
                }
            return {
                "code": code, "date": date,
                "power": 6609, "pct": -0.8, "m_net": 100, "amount": 1, "zt": 2, "sort": 1,
            }

        monkeypatch.setattr(mb, "plate_info", fake_plate)

        out = fb.snapshot()
        assert out["available"] is True
        assert out["as_of"] == "2026-09-12"
        assert out["prev"] == "2026-09-11"
        assert len(out["blocks"]) == 1
        b = out["blocks"][0]
        assert b["name"] == "通信"
        assert set(b["tags"]) == {"hot", "follow"}
        assert b["today"]["power"] == 500
        assert b["yesterday"]["power"] == 6609
        assert b["today"]["pct"] == 1.2
        assert b["yesterday"]["pct"] == -0.8
