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
from ths_block import processor as bp


def _fake_snapshot() -> dict:
    return {
        "updated_at": "2026-08-27 12:00:00",
        "ths_dir": "/tmp/ths",
        "kinds": {
            "conception": {
                "kind": "conception",
                "kind_label": "概念",
                "blocks": {"D001": "华为概念", "D002": "存储芯片"},
                "rows": [
                    {"kind": "conception", "kind_label": "概念", "id": "D001", "name": "华为概念"},
                    {"kind": "conception", "kind_label": "概念", "id": "D002", "name": "存储芯片"},
                ],
            },
            "industry": {
                "kind": "industry",
                "kind_label": "行业",
                "blocks": {"I001": "半导体", "I002": "华为概念"},
                "rows": [
                    {"kind": "industry", "kind_label": "行业", "id": "I001", "name": "半导体"},
                    {"kind": "industry", "kind_label": "行业", "id": "I002", "name": "华为概念"},
                ],
            },
        },
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
    names = {c["name"] for c in pending[0]["candidates"]}
    assert "华为概念" in names


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
