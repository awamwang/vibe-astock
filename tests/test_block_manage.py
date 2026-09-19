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


def test_merge_fuses_concept_tabs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "duanxian.block_dialect.canonicalize_name",
        lambda raw, region=False: str(raw or "").replace(" ", "").strip(),
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

    conception = merged["conception"]
    assert len(conception) == 2
    hit = next(r for r in conception if r["name"] == "通信")
    assert hit["origin"] == "ths"
    assert hit["kind"] == "conception"
    assert hit["id"] == "D574"
    assert hit["code"] == "885001"
    # 同名补字段；开盘啦独有概念并入同一页签
    assert hit["kpl_code"] == "801660"
    assert hit["has_kpl"] is True
    assert hit["kpl_name"] == "通信"
    only_kpl = next(r for r in conception if r["name"] == "AI应用")
    assert only_kpl["origin"] == "kpl"
    assert only_kpl["kind"] == "conception"
    assert only_kpl["kpl_code"] == "886100"
    assert only_kpl["kpl_name"] == "AI应用"

    hot_rows = merged["hot"]
    assert len(hot_rows) == 1
    assert hot_rows[0]["origin"] == "kpl"
    assert hot_rows[0]["kind"] == "hot"
    assert hot_rows[0]["kpl_code"] == "801660"
    assert hot_rows[0]["ths_kind"] == "conception"
    assert hot_rows[0]["id"] == "D574"


def test_merge_includes_theme_tab():
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {"rows": []},
            "industry": {"rows": []},
            "region": {"rows": []},
            "custom": {"rows": []},
            "daily": {"rows": []},
            "theme": {
                "rows": [{
                    "kind": "theme",
                    "kind_label": "热点主题",
                    "id": "B097",
                    "name": "光模块",
                    "node_type": "leaf",
                    "tree_path": "热点主题 › 共封装光学(CPO) › 光模块",
                    "theme_key": "光模块/CPO",
                    "root_id": "C0CD",
                    "block_type": "concept-subdivision",
                    "stock_count": 50,
                }],
            },
        },
    }
    kpl_snap = {
        "kinds": {
            "concept": {
                "rows": [{
                    "kind": "concept",
                    "kind_label": "概念",
                    "code": "886200",
                    "name": "光模块",
                    "power": 88,
                    "pct": 1.2,
                    "speed": 0.1,
                    "m_net": 1,
                    "sort": 1,
                }],
            },
            "hot": {
                "rows": [{
                    "kind": "hot",
                    "kind_label": "人气",
                    "code": "801200",
                    "name": "光模块/CPO",
                    "power": 100,
                    "pct": 0.5,
                    "speed": 0,
                    "m_net": 0,
                    "sort": 2,
                }],
            },
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    theme_rows = merged["theme"]
    assert len(theme_rows) == 1
    assert theme_rows[0]["origin"] == "ths"
    assert theme_rows[0]["kind"] == "theme"
    assert theme_rows[0]["ths_kind"] == "theme"
    assert theme_rows[0]["theme_key"] == "光模块/CPO"
    assert theme_rows[0]["root_id"] == "C0CD"
    assert theme_rows[0]["has_ths"] is True
    assert theme_rows[0]["has_kpl"] is True
    assert theme_rows[0]["kpl_code"] == "886200"


def test_merge_region_strips_admin_suffix():
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {"rows": []},
            "industry": {"rows": []},
            "region": {
                "rows": [{
                    "kind": "region",
                    "kind_label": "地域",
                    "id": "R001",
                    "name": "广东",
                    "code": "882001",
                    "node_type": "leaf",
                    "tree_path": "地域 › 广东",
                }],
            },
            "custom": {"rows": []},
            "daily": {"rows": []},
        },
    }
    kpl_snap = {
        "kinds": {
            "region": {
                "rows": [{
                    "kind": "region",
                    "kind_label": "地域",
                    "code": "880001",
                    "name": "广东省",
                    "power": 1,
                    "pct": 0.1,
                    "speed": 0,
                    "m_net": 0,
                    "sort": 1,
                }],
            },
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    region_rows = merged["region"]
    assert len(region_rows) == 1
    assert region_rows[0]["name"] == "广东"
    assert region_rows[0]["id"] == "R001"
    assert region_rows[0]["kpl_code"] == "880001"
    assert region_rows[0]["kpl_name"] == "广东省"
    assert region_rows[0]["has_ths"] is True
    assert region_rows[0]["has_kpl"] is True


def test_merge_exact_name_and_alias(monkeypatch: pytest.MonkeyPatch):
    """完全同名合并；别名族（酿酒→白酒）也能合并，并保留开盘啦原始名。"""
    monkeypatch.setattr(
        "duanxian.theme_normalize.load_aliases",
        lambda: {"酿酒": "白酒"},
    )
    monkeypatch.setattr(
        "duanxian.theme_normalize.canonicalize_tag",
        lambda tag, aliases=None: {"酿酒": "白酒"}.get(
            str(tag or "").replace(" ", "").strip(),
            str(tag or "").replace(" ", "").strip(),
        ),
    )
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {"rows": []},
            "industry": {
                "rows": [
                    {
                        "kind": "industry",
                        "kind_label": "行业",
                        "id": "BC03",
                        "name": "白酒",
                        "node_type": "leaf",
                        "tree_path": "行业 › 食品饮料 › 白酒",
                    },
                    {
                        "kind": "industry",
                        "kind_label": "行业",
                        "id": "DFAF",
                        "name": "白色家电",
                        "node_type": "leaf",
                        "tree_path": "行业 › 白色家电",
                    },
                    {
                        # 仅有分组同名也应吃掉开盘啦，避免重复行
                        "kind": "industry",
                        "kind_label": "行业",
                        "id": "DF09",
                        "name": "半导体",
                        "node_type": "branch",
                        "tree_path": "行业 › 半导体",
                    },
                ],
            },
            "region": {"rows": []},
            "custom": {"rows": []},
            "daily": {"rows": []},
        },
    }
    kpl_snap = {
        "kinds": {
            "industry": {
                "rows": [
                    {
                        "kind": "industry",
                        "kind_label": "行业",
                        "code": "881273",
                        "name": "酿酒",
                        "power": 1,
                        "pct": 0,
                        "speed": 0,
                        "m_net": 0,
                        "sort": 1,
                    },
                    {
                        "kind": "industry",
                        "kind_label": "行业",
                        "code": "881131",
                        "name": "白色家电",
                        "power": 1,
                        "pct": 0,
                        "speed": 0,
                        "m_net": 0,
                        "sort": 2,
                    },
                    {
                        "kind": "industry",
                        "kind_label": "行业",
                        "code": "881121",
                        "name": "半导体",
                        "power": 1,
                        "pct": 0,
                        "speed": 0,
                        "m_net": 0,
                        "sort": 3,
                    },
                ],
            },
            "hot": {"rows": []},
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    industry = merged["industry"]
    assert len(industry) == 3

    baijiu = next(r for r in industry if r["id"] == "BC03")
    assert baijiu["has_ths"] and baijiu["has_kpl"]
    assert baijiu["kpl_code"] == "881273"
    assert baijiu["kpl_name"] == "酿酒"
    assert baijiu["name"] == "白酒"

    white = next(r for r in industry if r["name"] == "白色家电")
    assert white["kpl_code"] == "881131"
    assert white["kpl_name"] == "白色家电"
    assert white["has_ths"] and white["has_kpl"]

    semi = next(r for r in industry if r["name"] == "半导体")
    assert semi["origin"] == "ths"
    assert semi["node_type"] == "branch"
    assert semi["kpl_code"] == "881121"
    assert semi["kpl_name"] == "半导体"
    assert not any(r.get("origin") == "kpl" and r.get("name") == "半导体" for r in industry)


def test_custom_matches_all_kpl_kinds(monkeypatch: pytest.MonkeyPatch):
    """自定义同花顺板块可与全部开盘啦类型同名匹配；不并入开盘啦独有行。"""
    monkeypatch.setattr(
        "duanxian.theme_normalize.load_aliases",
        lambda: {"酿酒": "白酒"},
    )
    monkeypatch.setattr(
        "duanxian.theme_normalize.canonicalize_tag",
        lambda tag, aliases=None: {"酿酒": "白酒"}.get(
            str(tag or "").replace(" ", "").strip(),
            str(tag or "").replace(" ", "").strip(),
        ),
    )
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {"rows": []},
            "industry": {"rows": []},
            "region": {"rows": []},
            "custom": {
                "rows": [
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "278",
                        "name": "AI应用",
                        "node_type": "flat",
                        "custom_type": "static",
                    },
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "279",
                        "name": "白酒",
                        "node_type": "flat",
                        "custom_type": "static",
                    },
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "280",
                        "name": "广东",
                        "node_type": "flat",
                        "custom_type": "static",
                    },
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "281",
                        "name": "人气龙头",
                        "node_type": "flat",
                        "custom_type": "dynamic",
                        "dynamic_kind": "watch",
                    },
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "282",
                        "name": "仅同花顺",
                        "node_type": "flat",
                        "custom_type": "static",
                    },
                ],
            },
            "daily": {"rows": []},
        },
    }
    kpl_snap = {
        "kinds": {
            "concept": {
                "rows": [{
                    "kind": "concept",
                    "kind_label": "概念",
                    "code": "886100",
                    "name": "AI应用",
                }],
            },
            "industry": {
                "rows": [{
                    "kind": "industry",
                    "kind_label": "行业",
                    "code": "881273",
                    "name": "酿酒",
                }],
            },
            "region": {
                "rows": [{
                    "kind": "region",
                    "kind_label": "地域",
                    "code": "880001",
                    "name": "广东省",
                }],
            },
            "hot": {
                "rows": [{
                    "kind": "hot",
                    "kind_label": "人气",
                    "code": "801001",
                    "name": "人气龙头",
                    "power": 99,
                }],
            },
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap=kpl_snap)
    custom = merged["custom"]
    assert len(custom) == 5
    assert not any(r.get("origin") == "kpl" for r in custom)

    ai = next(r for r in custom if r["id"] == "278")
    assert ai["has_kpl"] is True
    assert ai["kpl_code"] == "886100"
    assert ai["kpl_kind"] == "concept"
    assert ai["kpl_name"] == "AI应用"

    baijiu = next(r for r in custom if r["id"] == "279")
    assert baijiu["kpl_code"] == "881273"
    assert baijiu["kpl_kind"] == "industry"
    assert baijiu["kpl_name"] == "酿酒"
    assert baijiu["name"] == "白酒"

    gd = next(r for r in custom if r["id"] == "280")
    assert gd["kpl_code"] == "880001"
    assert gd["kpl_kind"] == "region"
    assert gd["kpl_name"] == "广东省"

    hot = next(r for r in custom if r["id"] == "281")
    assert hot["kpl_code"] == "801001"
    assert hot["kpl_kind"] == "hot"
    assert hot["kpl_power"] == 99

    only = next(r for r in custom if r["id"] == "282")
    assert only["has_kpl"] is False
    assert only["kpl_code"] == ""


def test_custom_color_fields_pass_through():
    """融合行保留同花顺自定义板块颜色与排序字段。"""
    ths_snap = {
        "kinds": {
            "conception": {"rows": []},
            "industry": {"rows": []},
            "region": {"rows": []},
            "custom": {
                "rows": [
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "278",
                        "name": "ABF",
                        "node_type": "flat",
                        "custom_type": "static",
                        "color": "#FF8F90",
                        "color_order": 4,
                        "color_priority": 1789693020,
                        "tree_order": 0,
                    },
                    {
                        "kind": "custom",
                        "kind_label": "自定义",
                        "id": "281",
                        "name": "无色",
                        "node_type": "flat",
                        "custom_type": "static",
                        "tree_order": 1,
                    },
                ],
            },
            "daily": {"rows": []},
            "theme": {"rows": []},
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap={"kinds": {}})
    colored = merged["custom"][0]
    assert colored["color"] == "#FF8F90"
    assert colored["color_order"] == 4
    assert colored["color_priority"] == 1789693020
    assert merged["custom"][1].get("color") in (None, "")


def test_merge_style_catalog_matches_ths_and_keeps_cons_meta():
    ths_snap = {
        "updated_at": "t",
        "kinds": {
            "conception": {
                "rows": [{
                    "kind": "conception",
                    "kind_label": "概念",
                    "id": "D815",
                    "name": "昨日涨停",
                    "code": "885815",
                    "node_type": "leaf",
                    "tree_path": "概念 › 昨日涨停",
                }],
            },
            "industry": {
                "rows": [{
                    "kind": "industry",
                    "kind_label": "行业",
                    "id": "BC10",
                    "name": "银行",
                    "node_type": "leaf",
                    "tree_path": "行业 › 银行",
                }],
            },
            "region": {"rows": []},
            "custom": {"rows": []},
            "daily": {"rows": []},
            "theme": {"rows": []},
        },
    }
    merged = block_manage.build_merged(ths_snap=ths_snap, kpl_snap={"kinds": {}})
    style_rows = merged["style"]
    leaves = [r for r in style_rows if r.get("style_key")]
    assert leaves
    assert all(r.get("node_type") != "branch" for r in style_rows)
    assert not any(str(r.get("id") or "").startswith("style_group:") for r in style_rows)

    yzt = next(r for r in leaves if r["style_key"] == "yzt")
    assert yzt["origin"] == "style"
    assert yzt["kind"] == "style"
    assert yzt["code"] == "BK0815"
    assert yzt["has_ths"] is True
    assert yzt["ths_kind"] == "conception"
    assert yzt["id"] == "D815"
    assert yzt["cons_available"] is True
    assert yzt["cons_source"] == "em_bk"
    assert yzt["style_group_label"] == "打板风格"
    assert yzt["parent_id"] == block_manage.STYLE_ROOT_ID

    bank = next(r for r in leaves if r["style_key"] == "bank")
    assert bank["has_ths"] is True
    assert bank["ths_kind"] == "industry"
    assert bank["id"] == "BC10"

    hs300 = next(r for r in leaves if r["style_key"] == "hs300")
    assert hs300["cons_source"] == "csindex"
    assert hs300["code"] == "000300"
    assert hs300["has_ths"] is False
    assert hs300["id"] == "style:hs300"

    cyb = next(r for r in leaves if r["style_key"] == "cyb")
    assert cyb["cons_source"] == "cnindex"
    assert cyb["code"] == "399006"

    hsi = next(r for r in leaves if r["style_key"] == "hsi")
    assert hsi["cons_available"] is False
    assert "恒生" in (hsi.get("cons_reason") or "")

    a50 = next(r for r in leaves if r["style_key"] == "a50")
    assert a50["cons_available"] is False
    assert "期指" in (a50.get("cons_reason") or "")

    emotion = next(r for r in leaves if r["style_key"] == "ths_emotion")
    assert emotion["cons_available"] is False
    assert emotion["name"] == "同花顺情绪指数"
    assert "公开" in (emotion.get("cons_reason") or "")


def _csi_singleton_payload(key="csi500"):
    return {
        "key": key,
        "name": "中证500",
        "code": "000905",
        "group": "benchmark",
        "available": True,
        "reason": None,
        "source": "csindex",
        "source_label": "中证成分文件",
        "note": None,
        "count": 1,
        "stocks": [{"code": "000905", "name": "中证500", "market": "SZ"}],
    }


def test_fetch_style_cons_falls_back_to_ths_name_match(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("duanxian.style_cons.fetch", lambda key: {
        "key": key, "name": "昨日涨停", "code": "BK0815", "group": "board",
        "available": False, "reason": "公开源失败", "source": "em_bk",
        "source_label": "东财板块成分", "note": None, "count": 0, "stocks": [],
    })
    monkeypatch.setattr("duanxian.block_manage._ths_snapshot", lambda: {
        "kinds": {"conception": {"rows": [{
            "kind": "conception", "id": "D815", "name": "昨日涨停", "node_type": "leaf",
        }]}}
    })
    monkeypatch.setattr(
        "ths_block.service.get_block_stocks",
        lambda **_k: {"stocks": [{"code": "600519", "name": "贵州茅台"}]},
    )
    out = block_manage.fetch_style_cons("yzt")
    assert out["available"] is True
    assert out["source"] == "ths"
    assert out["count"] == 1
    assert out["stocks"][0]["code"] == "600519"
    assert "补位" in (out.get("note") or "")


def test_fetch_style_cons_falls_back_when_csindex_is_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("duanxian.style_cons.fetch", lambda key: _csi_singleton_payload(key))
    monkeypatch.setattr("duanxian.block_manage._ths_snapshot", lambda: {
        "kinds": {"conception": {"rows": [{
            "kind": "conception", "id": "D905", "name": "中证500", "node_type": "leaf",
        }]}}
    })
    monkeypatch.setattr(
        "ths_block.service.get_block_stocks",
        lambda **_k: {"stocks": [
            {"code": "000009", "name": "中国宝安"},
            {"code": "000012", "name": "南玻A"},
        ]},
    )
    out = block_manage.fetch_style_cons("csi500")
    assert out["available"] is True
    assert out["source"] == "ths"
    assert out["count"] == 2


def test_fetch_style_cons_matches_ths_via_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "duanxian.theme_normalize.load_aliases",
        lambda: {"中证500指数": "中证500"},
    )
    monkeypatch.setattr("duanxian.style_cons.fetch", lambda key: _csi_singleton_payload(key))
    monkeypatch.setattr("duanxian.block_manage._ths_snapshot", lambda: {
        "kinds": {"conception": {"rows": [{
            "kind": "conception", "id": "D905", "name": "中证500指数", "node_type": "leaf",
        }]}}
    })
    monkeypatch.setattr(
        "ths_block.service.get_block_stocks",
        lambda **kw: {"stocks": [{"code": "000009", "name": "中国宝安"}]},
    )
    out = block_manage.fetch_style_cons("csi500")
    assert out["source"] == "ths"
    assert out["stocks"][0]["code"] == "000009"


def test_fetch_style_cons_keeps_usable_public(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("duanxian.style_cons.fetch", lambda key: {
        "key": key, "name": "昨日涨停", "code": "BK0815", "group": "board",
        "available": True, "reason": None, "source": "em_bk",
        "source_label": "东财板块成分", "note": None, "count": 2,
        "stocks": [
            {"code": "600519", "name": "贵州茅台", "market": "SH"},
            {"code": "000001", "name": "平安银行", "market": "SZ"},
        ],
    })

    def boom(**_k):
        raise AssertionError("公开源可用时不应补位同花顺")

    monkeypatch.setattr("ths_block.service.get_block_stocks", boom)
    out = block_manage.fetch_style_cons("yzt")
    assert out["source"] == "em_bk"
    assert out["count"] == 2

