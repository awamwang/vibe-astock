"""板块管理：开盘啦日限缓存 + 同花顺/开盘啦融合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from duanxian import block_manage, kpl_blocks


@pytest.fixture(autouse=True)
def _isolate_kpl_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path / "kpl_blocks"
    cache_dir.mkdir()
    monkeypatch.setattr(kpl_blocks, "_CACHE_DIR", str(cache_dir))
    with kpl_blocks._LOCK:
        kpl_blocks._mem = None
    yield
    with kpl_blocks._LOCK:
        kpl_blocks._mem = None


def test_kpl_ensure_reuses_today_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    today = "2026-09-13"
    monkeypatch.setattr(kpl_blocks, "china_today", lambda: today)
    payload = {
        "updated_at": "2026-09-13 10:00:00",
        "fetched_date": today,
        "kinds": {
            "concept": {
                "kind": "concept",
                "kind_label": "概念",
                "zs_type": 5,
                "count": 1,
                "api_count": 1,
                "rows": [{
                    "kind": "concept",
                    "kind_label": "概念",
                    "code": "886001",
                    "name": "测试概念",
                    "power": 100,
                    "pct": 1.2,
                    "speed": 0.1,
                    "m_net": 1,
                    "sort": 1,
                    "node_type": "flat",
                    "tree_path": "测试概念",
                }],
            },
        },
        "errors": [],
        "available": True,
        "from_cache": False,
    }
    path = Path(kpl_blocks._CACHE_DIR) / f"{today}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    called = {"n": 0}

    def boom():
        called["n"] += 1
        raise AssertionError("不应联网")

    monkeypatch.setattr(kpl_blocks, "_fetch_all", boom)
    out = kpl_blocks.ensure(force=False)
    assert out["available"] is True
    assert out["from_cache"] is True
    assert called["n"] == 0
    assert out["kinds"]["concept"]["count"] == 1


def test_kpl_ensure_force_refetches(monkeypatch: pytest.MonkeyPatch):
    today = "2026-09-13"
    monkeypatch.setattr(kpl_blocks, "china_today", lambda: today)
    monkeypatch.setattr(
        kpl_blocks,
        "_fetch_all",
        lambda: {
            "updated_at": "2026-09-13 12:00:00",
            "fetched_date": today,
            "kinds": {
                "hot": {
                    "kind": "hot",
                    "kind_label": "人气",
                    "zs_type": 7,
                    "count": 1,
                    "api_count": 1,
                    "rows": [{
                        "kind": "hot",
                        "kind_label": "人气",
                        "code": "801660",
                        "name": "通信",
                        "power": 6609,
                        "pct": 0.5,
                        "speed": 0.1,
                        "m_net": 1,
                        "sort": 1,
                        "node_type": "flat",
                        "tree_path": "通信",
                    }],
                },
            },
            "errors": [],
            "available": True,
            "from_cache": False,
        },
    )
    monkeypatch.setattr(kpl_blocks, "_save_archive", lambda _p: None)
    out = kpl_blocks.ensure(force=True)
    assert out["kinds"]["hot"]["rows"][0]["code"] == "801660"


def test_merge_keeps_original_type_tabs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "duanxian.block_dialect.canonicalize_name",
        lambda raw: str(raw or "").replace(" ", "").strip(),
    )
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {
                "rows": [{
                    "kind": "conception",
                    "kind_label": "概念",
                    "id": "D574",
                    "name": "通信",
                    "code": "885001",
                    "node_type": "leaf",
                    "tree_path": "概念 › 通信",
                    "depth": 1,
                    "stock_count": 12,
                }],
            },
            "industry": {"rows": []},
            "region": {"rows": []},
            "custom": {"rows": []},
            "daily": {"rows": []},
        },
    }
    kpl_snap = {
        "kinds": {
            "hot": {
                "rows": [{
                    "kind": "hot",
                    "kind_label": "人气",
                    "code": "801660",
                    "name": "通信",
                    "power": 6609,
                    "pct": 0.45,
                    "speed": 0.1,
                    "m_net": 100,
                    "sort": 1,
                }],
            },
            "concept": {
                "rows": [{
                    "kind": "concept",
                    "kind_label": "概念",
                    "code": "886100",
                    "name": "AI应用",
                    "power": 10,
                    "pct": 1.0,
                    "speed": 0.0,
                    "m_net": 0,
                    "sort": 2,
                }],
            },
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)

    ths_conception = merged["ths:conception"]
    assert len(ths_conception) == 1
    hit = ths_conception[0]
    assert hit["origin"] == "ths"
    assert hit["kind"] == "conception"
    assert hit["id"] == "D574"
    assert hit["code"] == "885001"
    # 同名仅补字段，不把开盘啦独有概念并入同花顺页签
    assert hit["kpl_code"] == "801660"
    assert hit["has_kpl"] is True
    assert all(r["name"] != "AI应用" for r in ths_conception)

    kpl_concept = merged["kpl:concept"]
    assert len(kpl_concept) == 1
    assert kpl_concept[0]["origin"] == "kpl"
    assert kpl_concept[0]["kind"] == "concept"
    assert kpl_concept[0]["kpl_code"] == "886100"

    hot_rows = merged["kpl:hot"]
    assert len(hot_rows) == 1
    assert hot_rows[0]["origin"] == "kpl"
    assert hot_rows[0]["kind"] == "hot"
    assert hot_rows[0]["kpl_code"] == "801660"
    # 人气页签可补同花顺字段，但不改变类型
    assert hot_rows[0]["ths_kind"] == "conception"
    assert hot_rows[0]["id"] == "D574"
