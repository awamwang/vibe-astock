"""板块处理器单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VR = ROOT / "vr"
if str(VR) not in sys.path:
    sys.path.insert(0, str(VR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ths_block import cache as block_cache
from ths_block import linker
from ths_block import processor as bp


def _fake_snapshot() -> dict:
    kinds: dict = {}
    for kind in linker.list_kinds():
        label = {"conception": "概念", "industry": "行业", "region": "地域", "custom": "自定义", "daily": "日线"}.get(kind, kind)
        if kind == "conception":
            blocks = {"D001": "华为概念", "D002": "存储芯片"}
        elif kind == "industry":
            blocks = {"I001": "半导体", "I002": "华为概念"}
        else:
            blocks = {f"{kind[:1].upper()}001": f"{label}样例"}
        rows = [
            {"kind": kind, "kind_label": label, "id": bid, "name": name}
            for bid, name in blocks.items()
        ]
        kinds[kind] = {"kind": kind, "kind_label": label, "blocks": blocks, "rows": rows}
    return {
        "updated_at": "2026-08-27 12:00:00",
        "ths_dir": "/tmp/ths",
        "kinds": kinds,
    }


@pytest.fixture(autouse=True)
def _reset_processor(monkeypatch: pytest.MonkeyPatch):
    bp.clear_pending()
    bp.invalidate_index()
    block_cache.set_snapshot(_fake_snapshot())
    monkeypatch.setattr(
        "duanxian.theme_normalize.canonicalize_tag",
        lambda tag, aliases=None: str(tag or "").replace(" ", "").strip(),
    )
    monkeypatch.setattr(
        "ths_block.service.refresh_kind",
        lambda *, kind, ths_dir=None: block_cache.get() or {},
    )


def test_exact_match_prefers_conception():
    r = bp.resolve_one("华为概念")
    assert r["status"] == "matched"
    assert r["block"]["kind"] == "conception"
    assert r["block"]["id"] == "D001"


def test_partial_match_recorded():
    bp.feed("emotion_industry", ["华为"])
    pending = bp.get_pending()
    assert len(pending) == 1
    assert pending[0]["status"] == "partial"
    assert pending[0]["raw"] == "华为"
    assert pending[0]["suggested_canonical"] == "华为概念"
    names = {c["name"] for c in pending[0]["candidates"]}
    assert "华为概念" in names


def test_multiple_exact_match_not_pending():
    r = bp.resolve_one("华为概念")
    assert r["status"] == "matched"
    assert len(r["candidates"]) >= 2
    bp.feed("firstboard_theme", ["华为概念"])
    assert bp.get_pending() == []


def test_partial_suggested_canonical_space_joined():
    snap = _fake_snapshot()
    snap["kinds"]["conception"]["blocks"]["D003"] = "人工合成"
    snap["kinds"]["conception"]["rows"].append(
        {"kind": "conception", "kind_label": "概念", "id": "D003", "name": "人工合成"},
    )
    snap["kinds"]["industry"]["blocks"]["I003"] = "人工成本"
    snap["kinds"]["industry"]["rows"].append(
        {"kind": "industry", "kind_label": "行业", "id": "I003", "name": "人工成本"},
    )
    block_cache.set_snapshot(snap)
    bp.invalidate_index()
    bp.feed("sector_flow", ["人工"])
    pending = bp.get_pending()
    assert len(pending) == 1
    assert pending[0]["suggested_canonical"] == "人工合成 人工成本"


def test_unmatched_recorded():
    bp.feed("mood_block", ["完全不存在的板块名"])
    pending = bp.get_pending()
    assert len(pending) == 1
    assert pending[0]["status"] == "unmatched"
    assert pending[0]["candidates"] == []


def test_dedupe_and_source_merge():
    bp.feed("sector_flow", ["存储"])
    bp.feed("firstboard_theme", ["存储"])
    pending = bp.get_pending()
    assert len(pending) == 1
    assert pending[0]["hit_count"] == 2
    assert "sector_flow" in pending[0]["sources"]
    assert "firstboard_theme" in pending[0]["sources"]


def test_message_target_not_in_pending():
    bp.feed("message_target", ["未知题材A"])
    bp.feed("emotion_industry", ["未知题材B"])
    pending = bp.get_pending()
    assert len(pending) == 1
    assert pending[0]["raw"] == "未知题材B"


def test_matched_not_in_pending():
    bp.feed("firstboard_industry", ["半导体"])
    assert bp.get_pending() == []


def test_remove_pending():
    bp.feed("mood_block", ["完全不存在的板块名"])
    assert bp.remove_pending(raw="完全不存在的板块名")
    assert bp.get_pending() == []


def test_ensure_kinds_cached_triggers_missing(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    called: list[str] = []

    def fake_refresh(*, kind: str, ths_dir=None):
        called.append(kind)
        snap = block_cache.get() or {"kinds": {}}
        kinds = dict(snap.get("kinds") or {})
        kinds[kind] = {
            "kind": kind,
            "kind_label": kind,
            "blocks": {"X1": "测试板块"},
            "rows": [{"kind": kind, "kind_label": kind, "id": "X1", "name": "测试板块"}],
        }
        block_cache.set_snapshot({"updated_at": "2026-08-27 13:00:00", "ths_dir": "/tmp", "kinds": kinds})
        return block_cache.get()

    monkeypatch.setattr("ths_block.service.refresh_kind", fake_refresh)
    bp.invalidate_index()
    refreshed = bp.ensure_kinds_cached()
    assert set(called) == set(linker.list_kinds())
    assert set(refreshed) == set(linker.list_kinds())


def test_ensure_kinds_cached_skips_when_complete(monkeypatch: pytest.MonkeyPatch):
    called: list[str] = []
    monkeypatch.setattr(
        "ths_block.service.refresh_kind",
        lambda *, kind, ths_dir=None: called.append(kind),
    )
    bp.invalidate_index()
    bp.ensure_kinds_cached()
    assert called == []
    bp.ensure_kinds_cached()
    assert called == []


def test_feed_skips_without_cache(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    bp.invalidate_index()
    called: list[str] = []

    def fake_refresh(*, kind: str, ths_dir=None):
        called.append(kind)
        return block_cache.get() or {}

    monkeypatch.setattr("ths_block.service.refresh_kind", fake_refresh)
    bp.feed("sector_flow", ["半导体"])
    assert called == []
    assert bp.get_pending() == []
    assert bp.feed_overview({"sectors": [{"name": "半导体"}]}) is None


def test_resolve_many_and_index_info():
    info = bp.index_info()
    assert info["ready"] is True
    assert info["complete"] is True
    assert info["name_count"] >= 3
    rows = bp.resolve_many(["华为概念", "半导体", "不存在"])
    assert len(rows) == 3
    assert rows[0]["status"] == "matched"
    assert rows[1]["status"] == "matched"
    assert rows[2]["status"] == "unmatched"
    exported = bp.export_resolve(["华为概念", "半导体"])
    assert "华为概念" in exported["by_raw"]
    assert exported["index"]["ready"] is True
    assert exported["index"]["complete"] is True


def test_scan_text_known_block_and_concept():
    rows = bp.scan_text("市场关注华为概念与存储芯片，另有AI液冷概念股异动。", feed_unmatched=True)
    matched_names = {
        (r.get("block") or {}).get("name")
        for r in rows
        if r.get("status") == "matched"
    }
    assert "华为概念" in matched_names
    assert "存储芯片" in matched_names
    pending = bp.get_pending()
    assert any(p.get("raw") == "AI液冷" or p.get("mapped") == "AI液冷" for p in pending)


def test_directory_nodes_not_indexed():
    """概念分类夹与行业/地域根名排除；行业父节点与具体地域保留。"""
    snap = _fake_snapshot()
    concept = snap["kinds"]["conception"]
    concept["blocks"].update(
        {
            "2B": "概念",
            "DBD0": "概念中的概念",
            "DBDG": "地域类",
            "DBCF": "价格驱动",
            "DBCE": "政策驱动",
            "DBCD": "科技类",
            "DBCC": "其它",
            "DBCB": "事件驱动",
            "DBCA": "工业类",
            "D010": "华为概念",
        }
    )
    concept["rows"] = [
        {
            "kind": "conception",
            "kind_label": "概念",
            "id": "2B",
            "name": "概念",
            "node_type": "branch",
        },
        {
            "kind": "conception",
            "kind_label": "概念",
            "id": "DBDG",
            "name": "地域类",
            "node_type": "branch",
        },
        {
            "kind": "conception",
            "kind_label": "概念",
            "id": "DBCF",
            "name": "价格驱动",
            "node_type": "branch",
        },
        {
            "kind": "conception",
            "kind_label": "概念",
            "id": "D010",
            "name": "华为概念",
            "node_type": "leaf",
        },
    ]
    industry = snap["kinds"]["industry"]
    industry["blocks"].update(
        {
            "DFF8": "行业",
            "DFB9": "半导体",
            "DF97": "银行",
            "BC83": "白酒",
        }
    )
    industry["rows"] = [
        {
            "kind": "industry",
            "kind_label": "行业",
            "id": "DFF8",
            "name": "行业",
            "node_type": "branch",
        },
        {
            "kind": "industry",
            "kind_label": "行业",
            "id": "DFB9",
            "name": "半导体",
            "node_type": "branch",
        },
        {
            "kind": "industry",
            "kind_label": "行业",
            "id": "DF97",
            "name": "银行",
            "node_type": "branch",
        },
        {
            "kind": "industry",
            "kind_label": "行业",
            "id": "BC83",
            "name": "白酒",
            "node_type": "branch",
        },
        {
            "kind": "industry",
            "kind_label": "行业",
            "id": "I001",
            "name": "半导体",
            "node_type": "leaf",
        },
    ]
    region = snap["kinds"]["region"]
    region["blocks"].update(
        {
            "47": "地域",
            "4D": "广东",
            "61": "上海",
            "48": "安徽",
        }
    )
    region["rows"] = [
        {
            "kind": "region",
            "kind_label": "地域",
            "id": "47",
            "name": "地域",
            "node_type": "branch",
        },
        {
            "kind": "region",
            "kind_label": "地域",
            "id": "4D",
            "name": "广东",
            "node_type": "branch",
        },
        {
            "kind": "region",
            "kind_label": "地域",
            "id": "61",
            "name": "上海",
            "node_type": "branch",
        },
        {
            "kind": "region",
            "kind_label": "地域",
            "id": "48",
            "name": "安徽",
            "node_type": "leaf",
        },
    ]
    block_cache.set_snapshot(snap)
    bp.invalidate_index()

    for raw in (
        "概念",
        "概念中的概念",
        "地域类",
        "价格驱动",
        "政策驱动",
        "科技类",
        "其它",
        "事件驱动",
        "工业类",
        "行业",
        "地域",
    ):
        r = bp.resolve_one(raw)
        assert r["status"] != "matched", raw
        assert r["block"] is None, raw

    ok = bp.resolve_one("华为概念")
    assert ok["status"] == "matched"
    assert ok["block"]["id"] == "D010"

    for raw, kind in (
        ("半导体", "industry"),
        ("银行", "industry"),
        ("白酒", "industry"),
        ("广东", "region"),
        ("上海", "region"),
        ("安徽", "region"),
    ):
        r = bp.resolve_one(raw)
        assert r["status"] == "matched", raw
        assert r["block"]["kind"] == kind, raw

    scanned = bp.scan_text(
        "行业与地域板块分化，关注价格驱动、半导体与广东、华为概念。",
        feed_unmatched=False,
    )
    matched = {
        (r.get("block") or {}).get("name")
        for r in scanned
        if r.get("status") == "matched"
    }
    assert matched == {"华为概念", "半导体", "广东"}


def test_schedule_ensure_kinds_cached_async(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    called: list[str] = []

    def fake_refresh(*, kind: str, ths_dir=None):
        called.append(kind)
        snap = block_cache.get() or {"kinds": {}}
        kinds = dict(snap.get("kinds") or {})
        kinds[kind] = {
            "kind": kind,
            "kind_label": kind,
            "blocks": {"X1": "测试板块"},
            "rows": [{"kind": kind, "kind_label": kind, "id": "X1", "name": "测试板块"}],
        }
        block_cache.set_snapshot({"updated_at": "2026-08-27 14:00:00", "ths_dir": "/tmp", "kinds": kinds})
        return block_cache.get()

    monkeypatch.setattr("ths_block.service.refresh_kind", fake_refresh)
    bp.invalidate_index()
    assert bp.schedule_ensure_kinds_cached() is True
    import time
    deadline = time.time() + 5
    while time.time() < deadline and len(called) < len(linker.list_kinds()):
        time.sleep(0.05)
    assert set(called) == set(linker.list_kinds())


def test_export_resolve_schedules_ensure(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    scheduled: list[bool] = []
    monkeypatch.setattr(
        "ths_block.processor.schedule_ensure_kinds_cached",
        lambda: scheduled.append(True) or True,
    )
    bp.invalidate_index()
    bp.export_resolve(["半导体"])
    assert scheduled


def test_linker_unavailable_skips_ensure_and_feed(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot(
        {
            "updated_at": "2026-08-27 15:00:00",
            "ths_dir": None,
            "kinds": {},
            "errors": ["linker: 未找到 ths-linker 命令"],
            "linker_unavailable": True,
            "linker_message": "依赖于第三方工具，目前无法请求",
        }
    )
    bp.invalidate_index()
    called: list[str] = []

    def fake_refresh(*, kind: str, ths_dir=None):
        called.append(kind)
        return block_cache.get() or {}

    monkeypatch.setattr("ths_block.service.refresh_kind", fake_refresh)
    assert bp.ensure_kinds_cached() == []
    assert called == []
    assert bp.schedule_ensure_kinds_cached() is False
    assert bp.feed("sector_flow", ["半导体"]) == []
    info = bp.index_info()
    assert info["linker_unavailable"] is True
    assert info["ready"] is False


def test_ensure_marks_unavailable_when_cli_missing(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    bp.invalidate_index()
    monkeypatch.setattr("ths_block.linker.is_cli_available", lambda: False)
    assert bp.ensure_kinds_cached() == []
    snap = block_cache.get() or {}
    assert snap.get("linker_unavailable") is True
    assert snap.get("linker_message") == "依赖于第三方工具，目前无法请求"

