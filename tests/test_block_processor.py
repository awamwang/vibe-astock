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


def test_message_target_sorted_last():
    bp.feed("message_target", ["未知题材A"])
    bp.feed("emotion_industry", ["未知题材B"])
    pending = bp.get_pending()
    assert pending[0]["raw"] == "未知题材B"
    assert pending[1]["raw"] == "未知题材A"


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

