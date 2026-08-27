"""同花顺板块解析与缓存单元测试。"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VR = ROOT / "vr"
if str(VR) not in sys.path:
    sys.path.insert(0, str(VR))

from ths_block import cache as block_cache
from ths_block import persist as block_persist
from ths_block import service as block_service
from ths_block import stocks as block_stocks
from ths_block import tree as block_tree


def _write_stockblock_ini(ths_dir: Path, filename: str, content: str) -> None:
    base = (
        ths_dir
        / "xiadan-plus"
        / "quote"
        / "config"
        / "quota"
        / "stockblock"
    )
    base.mkdir(parents=True, exist_ok=True)
    (base / filename).write_text(content, encoding="gbk")


def _make_ths_fixture(tmp_path: Path) -> Path:
    ths = tmp_path / "ths"
    ths.mkdir()
    _write_stockblock_ini(
        ths,
        "block_conception.ini",
        "[ConfigInfo]\r\n"
        "[BLOCK_NAME_MAP_TABLE]\r\n"
        "D574=华为概念\r\n"
        "CFE6=智能电网\r\n"
        "[BLOCK_STOCK_CONTEXT]\r\n"
        "D574=17:600519,33:000001\r\n"
        "CFE6=33:000021,33:000333\r\n",
    )
    user_dir = ths / "testuser"
    cb = user_dir / "custom_block"
    cb.mkdir(parents=True)
    ln = base64.b64encode("测试板块".encode("gbk")).decode("ascii")
    (cb / "278").write_text(
        json.dumps({"ln": ln, "context": "603186|000001|"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (ths / "users.ini").write_text(
        "[last_userid]\r\nlast_userid=1\r\n[users]\r\n1=测试,testuser\r\n",
        encoding="gbk",
    )
    return ths


def _write_block_tree_ini(ths_dir: Path, content: str) -> None:
    base = ths_dir / "BlockUpdate"
    base.mkdir(parents=True, exist_ok=True)
    (base / "block_tree.ini").write_text(content, encoding="gbk")


def _make_nested_tree_fixture(tmp_path: Path) -> Path:
    """新版 block_tree.ini：根节点嵌套在 [@10001] 下。"""
    ths = _make_ths_fixture(tmp_path)
    _write_block_tree_ini(
        ths,
        "[BLOCK_TREE_ROOT]\r\n"
        "1=@10001\r\n"
        "[@10001]\r\n"
        "2B=@10043\r\n"
        "[@10043]\r\n"
        "DBD0=@10044\r\n"
        "D574=536871427\r\n"
        "[@10044]\r\n"
        "CFE6=536871427\r\n",
    )
    return ths


def test_parse_system_block_stocks(tmp_path: Path):
    ths = _make_ths_fixture(tmp_path)
    items = block_stocks.list_block_stocks(ths, kind="conception", block_id="D574")
    codes = [x["code"] for x in items]
    assert codes == ["600519", "000001"]


def test_parse_custom_block_stocks(tmp_path: Path):
    ths = _make_ths_fixture(tmp_path)
    items = block_stocks.list_block_stocks(ths, kind="custom", block_id="278")
    codes = [x["code"] for x in items]
    assert codes == ["603186", "000001"]


def test_cache_refresh_with_mock_linker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ths = _make_ths_fixture(tmp_path)
    ths_str = str(ths)

    def fake_list(kind: str, *, ths_dir: str | None = None):
        mapping = {
            "custom": {
                "278": {
                    "name": "测试板块",
                    "custom_type": "static",
                    "hex_id": "116",
                    "stock_count": 2,
                },
                "233": {
                    "name": "营业部动态",
                    "custom_type": "dynamic",
                    "dynamic_kind": "broker",
                    "query_key": "测试营业部",
                    "hex_id": "E9",
                },
            },
            "conception": {"D574": "华为概念", "CFE6": "智能电网"},
            "industry": {"C6AC": "IT服务Ⅲ"},
            "region": {"48": "安徽"},
            "daily": {"D326": "昨日涨停板块"},
        }
        labels = {
            "custom": "自定义板块",
            "conception": "概念",
            "industry": "行业",
            "region": "地域",
            "daily": "每日动态",
        }
        blocks = mapping[kind]
        return {
            "ok": True,
            "action": "list",
            "kind": kind,
            "kind_label": labels[kind],
            "count": len(blocks),
            "blocks": blocks,
        }

    def fake_tree(kind: str, *, ths_dir: str | None = None):
        return {
            "ok": True,
            "action": "tree",
            "kind": kind,
            "kind_label": {"conception": "概念", "industry": "行业", "region": "地域"}[kind],
            "root_id": "2B",
            "root_name": "概念",
            "branch_count": 2,
            "leaf_count": 1,
            "tree": {
                "id": "2B",
                "name": "概念",
                "node_type": "branch",
                "children": [
                    {
                        "id": "DBD0",
                        "name": "技术分组",
                        "node_type": "branch",
                        "children": [
                            {"id": "CFE6", "name": "智能电网", "node_type": "leaf"},
                        ],
                    },
                    {"id": "D574", "name": "华为概念", "node_type": "leaf"},
                ],
            },
        }

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: ths_str)
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)
    monkeypatch.setattr("ths_block.linker.fetch_tree", fake_tree)

    snap = block_service.refresh_cache()
    assert snap["ths_dir"] == ths_str
    assert "conception" in snap["kinds"]
    rows = snap["kinds"]["conception"]["rows"]
    assert any(r["id"] == "D574" and r["node_type"] == "leaf" for r in rows)
    assert any(r["id"] == "DBD0" and r["node_type"] == "branch" for r in rows)
    d574 = next(r for r in rows if r["id"] == "D574")
    assert d574["depth"] == 1
    assert d574["parent_id"] == "2B"
    assert "tree_order" in d574

    custom_rows = snap["kinds"]["custom"]["rows"]
    static_row = next(r for r in custom_rows if r["id"] == "278")
    assert static_row["custom_type"] == "static"
    assert static_row["hex_id"] == "116"
    dynamic_row = next(r for r in custom_rows if r["id"] == "233")
    assert dynamic_row["custom_type"] == "dynamic"
    assert dynamic_row["dynamic_kind"] == "broker"
    assert dynamic_row["query_key"] == "测试营业部"

    detail = block_service.get_block_stocks(kind="conception", block_id="D574")
    assert detail["count"] == 2
    assert detail["stocks"][0]["code"] == "600519"

    block_cache.set_snapshot({})
    with pytest.raises(RuntimeError, match="请先点击刷新"):
        block_service.get_block_stocks(kind="conception", block_id="D574")


def test_extract_dynamic_blocks_only():
    entry = {
        "blocks": {
            "278": "测试板块",
            "233": "营业部动态",
        },
        "blocks_meta": {
            "278": {
                "name": "测试板块",
                "custom_type": "static",
                "hex_id": "116",
                "stock_count": 2,
            },
            "233": {
                "name": "营业部动态",
                "custom_type": "dynamic",
                "dynamic_kind": "broker",
                "query_key": "测试营业部",
                "hex_id": "E9",
            },
            "239": {
                "name": "人工智能+消费电子",
                "custom_type": "dynamic",
                "dynamic_kind": "concept",
                "query_key": "人工智能+消费电子",
                "hex_id": "EF",
                "stock_count": 125,
            },
        },
    }
    blocks = block_persist.extract_dynamic_blocks(entry)
    assert set(blocks) == {"233", "239"}
    assert blocks["233"]["dynamic_kind"] == "broker"
    assert blocks["239"]["stock_count"] == 125
    assert "278" not in blocks


def test_save_dynamic_custom_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "同花顺自定义板块.json"
    monkeypatch.setenv("THS_CUSTOM_BLOCKS_JSON", str(target))
    entry = {
        "blocks_meta": {
            "233": {
                "name": "营业部动态",
                "custom_type": "dynamic",
                "dynamic_kind": "broker",
                "query_key": "测试营业部",
                "hex_id": "E9",
            },
        },
    }
    payload = block_persist.save_dynamic_custom_blocks(
        ths_dir="S:\\同花顺软件\\同花顺",
        entry=entry,
    )
    assert payload["count"] == 1
    assert payload["blocks"]["233"]["name"] == "营业部动态"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["count"] == 1
    assert saved["ths_dir"] == "S:\\同花顺软件\\同花顺"
    assert saved["blocks"]["233"]["dynamic_kind"] == "broker"


def test_refresh_custom_persists_dynamic_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ths = _make_ths_fixture(tmp_path)
    ths_str = str(ths)
    target = tmp_path / "同花顺自定义板块.json"
    monkeypatch.setenv("THS_CUSTOM_BLOCKS_JSON", str(target))

    def fake_list(kind: str, *, ths_dir: str | None = None):
        if kind != "custom":
            return {
                "ok": True,
                "action": "list",
                "kind": kind,
                "kind_label": kind,
                "count": 0,
                "blocks": {},
            }
        return {
            "ok": True,
            "action": "list",
            "kind": "custom",
            "kind_label": "自定义板块",
            "count": 2,
            "blocks": {
                "278": {
                    "name": "测试板块",
                    "custom_type": "static",
                    "hex_id": "116",
                },
                "233": {
                    "name": "营业部动态",
                    "custom_type": "dynamic",
                    "dynamic_kind": "broker",
                    "query_key": "测试营业部",
                    "hex_id": "E9",
                },
            },
        }

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: ths_str)
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)

    block_service.refresh_kind(kind="custom")
    assert target.is_file()
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["count"] == 1
    assert "233" in saved["blocks"]
    assert "278" not in saved["blocks"]


def test_tree_fallback_to_flat_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ths = _make_ths_fixture(tmp_path)
    ths_str = str(ths)

    def fake_list(kind: str, *, ths_dir: str | None = None):
        return {
            "ok": True,
            "action": "list",
            "kind": kind,
            "kind_label": "概念",
            "count": 1,
            "blocks": {"D574": "华为概念"},
        }

    def fake_tree_fail(kind: str, *, ths_dir: str | None = None):
        raise RuntimeError("板块树缺失 conception 根节点")

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: ths_str)
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)
    monkeypatch.setattr("ths_block.linker.fetch_tree", fake_tree_fail)

    snap = block_service.refresh_cache()
    entry = snap["kinds"]["conception"]
    assert entry["tree_mode"] == "flat_fallback"
    assert len(entry["rows"]) == 1
    assert entry["rows"][0]["id"] == "D574"
    assert any("树结构不可用" in e for e in snap["errors"])


def test_build_block_tree_nested_root(tmp_path: Path):
    ths = _make_nested_tree_fixture(tmp_path)
    result = block_tree.build_block_tree(
        ths,
        "conception",
        names={"2B": "概念", "DBD0": "技术分组", "D574": "华为概念", "CFE6": "智能电网"},
    )
    assert result["root_id"] == "2B"
    assert result["leaf_count"] == 2
    branch = next(c for c in result["tree"]["children"] if c["id"] == "DBD0")
    assert branch["node_type"] == "branch"
    assert branch["children"][0]["id"] == "CFE6"


def test_refresh_uses_local_tree_with_nested_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ths = _make_nested_tree_fixture(tmp_path)
    ths_str = str(ths)

    def fake_list(kind: str, *, ths_dir: str | None = None):
        return {
            "ok": True,
            "action": "list",
            "kind": kind,
            "kind_label": "概念",
            "count": 4,
            "blocks": {
                "2B": "概念",
                "DBD0": "技术分组",
                "D574": "华为概念",
                "CFE6": "智能电网",
            },
        }

    def fake_tree_fail(kind: str, *, ths_dir: str | None = None):
        raise RuntimeError("板块树缺少 conception 根节点 2B 的子树引用")

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: ths_str)
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)
    monkeypatch.setattr("ths_block.linker.fetch_tree", fake_tree_fail)

    snap = block_service.refresh_kind(kind="conception")
    entry = snap["kinds"]["conception"]
    assert entry["tree_mode"] == "tree"
    assert entry["root_id"] == "2B"
    assert not any("conception:" in e and "flat 列表" in e for e in snap.get("errors") or [])
