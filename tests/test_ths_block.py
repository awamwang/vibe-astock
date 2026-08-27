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
from ths_block import service as block_service
from ths_block import stocks as block_stocks


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
