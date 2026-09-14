"""同花顺板块解析与缓存单元测试。"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VR = ROOT / "vr"
if str(VR) not in sys.path:
    sys.path.insert(0, str(VR))

from ths_block import cache as block_cache
from ths_block import persist as block_persist
from ths_block import processor as block_processor
from ths_block import service as block_service
from ths_block import stocks as block_stocks
from ths_block import theme_daily
from ths_block import tree as block_tree


@pytest.fixture(autouse=True)
def _isolate_theme_daily(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path_factory.mktemp("ths_theme")
    monkeypatch.setattr(theme_daily, "_CACHE_DIR", str(cache_dir))
    theme_daily.clear_mem()
    yield
    theme_daily.clear_mem()


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
            "conception": {
                "D574": {"name": "华为概念", "code": "885788"},
                "CFE6": {"name": "智能电网", "code": "885775"},
            },
            "industry": {"C6AC": {"name": "IT服务Ⅲ", "code": "881271"}},
            "region": {"48": {"name": "安徽", "code": "882001"}},
            "daily": {"D326": {"name": "昨日涨停板块", "code": "883900"}},
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
    monkeypatch.setattr(
        "ths_block.linker.fetch_theme_list",
        lambda **_kw: {"ok": True, "action": "list", "source": "local", "blocks": {}},
    )

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
    assert d574["code"] == "885788"
    cfe6 = next(r for r in rows if r["id"] == "CFE6")
    assert cfe6["code"] == "885775"

    daily_rows = snap["kinds"]["daily"]["rows"]
    d326 = next(r for r in daily_rows if r["id"] == "D326")
    assert d326["code"] == "883900"
    assert d326["name"] == "昨日涨停板块"

    custom_rows = snap["kinds"]["custom"]["rows"]
    static_row = next(r for r in custom_rows if r["id"] == "278")
    assert static_row["custom_type"] == "static"
    assert static_row["hex_id"] == "116"
    assert "code" not in static_row
    dynamic_row = next(r for r in custom_rows if r["id"] == "233")
    assert dynamic_row["custom_type"] == "dynamic"
    assert dynamic_row["dynamic_kind"] == "broker"
    assert dynamic_row["query_key"] == "测试营业部"

    detail = block_service.get_block_stocks(kind="conception", block_id="D574")
    assert detail["count"] == 2
    assert detail["stocks"][0]["code"] == "600519"
    assert detail["code"] == "885788"

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
    monkeypatch.setattr(
        "ths_block.linker.fetch_theme_list",
        lambda **_kw: {"ok": True, "action": "list", "source": "local", "blocks": {}},
    )

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


def test_refresh_and_ensure_no_deadlock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """后台 ensure 与用户 refresh 并发时不应死锁。"""
    ths = _make_ths_fixture(tmp_path)
    ths_str = str(ths)
    block_cache.set_snapshot({})
    block_processor.invalidate_index()

    def fake_list(kind: str, *, ths_dir: str | None = None):
        time.sleep(0.05)
        return {
            "ok": True,
            "action": "list",
            "kind": kind,
            "kind_label": kind,
            "count": 1,
            "blocks": {f"{kind[:1].upper()}001": f"{kind}样例"},
        }

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: ths_str)
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)
    monkeypatch.setattr(
        "ths_block.linker.fetch_tree",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setattr(
        "ths_block.linker.fetch_theme_list",
        lambda **_kw: {"ok": True, "action": "list", "source": "local", "blocks": {}},
    )

    ensure_done = threading.Event()
    ensure_error: list[BaseException] = []

    def run_ensure() -> None:
        try:
            block_processor.ensure_kinds_cached()
        except BaseException as exc:  # noqa: BLE001
            ensure_error.append(exc)
        finally:
            ensure_done.set()

    threading.Thread(target=run_ensure, daemon=True).start()
    time.sleep(0.02)
    block_service.refresh_kind(kind="conception")

    assert ensure_done.wait(timeout=5), "ensure_kinds_cached 与 refresh_kind 发生死锁"
    assert not ensure_error


def test_refresh_cache_marks_linker_unavailable(monkeypatch: pytest.MonkeyPatch):
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})

    def fake_list(kind: str, *, ths_dir: str | None = None):
        raise RuntimeError("未找到 ths-linker 命令，请先安装并加入 PATH")

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: "/tmp/ths")
    monkeypatch.setattr("ths_block.linker.fetch_list", fake_list)
    monkeypatch.setattr(
        "ths_block.linker.fetch_theme_list",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("未找到 ths-linker 命令，请先安装并加入 PATH")),
    )

    snap = block_service.refresh_cache()
    assert snap.get("linker_unavailable") is True
    assert snap.get("linker_message") == "依赖于第三方工具，目前无法请求"
    # 各类型均失败时不应残留可用板块数据
    assert not any(
        (isinstance(v.get("blocks"), dict) and v["blocks"])
        or (isinstance(v.get("rows"), list) and v["rows"])
        for v in (snap.get("kinds") or {}).values()
        if isinstance(v, dict)
    )

def test_refresh_theme_kind_builds_forest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """热点主题：list + 各主题 tree 合成森林，成分股走 ths-theme stocks。"""
    from ths_block import theme_daily

    cache_dir = tmp_path / "ths_theme"
    cache_dir.mkdir()
    monkeypatch.setattr(theme_daily, "_CACHE_DIR", str(cache_dir))
    theme_daily.clear_mem()
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})

    def fake_theme_list(*, ths_dir=None, source="auto", tab="all"):
        if source == "online":
            raise RuntimeError("offline")
        return {
            "ok": True,
            "action": "list",
            "source": "local",
            "kind": "theme",
            "kind_label": "热点主题",
            "count": 1,
            "blocks": {
                "C0CD": {
                    "name": "共封装光学(CPO)",
                    "block_type": "hot-theme",
                    "is_ths_block": True,
                    "stock_count": 0,
                },
            },
        }

    def fake_theme_tree(*, ths_dir=None, theme_key=None, root_id=None, source="auto"):
        assert root_id == "C0CD" or theme_key
        return {
            "ok": True,
            "action": "tree",
            "source": "local",
            "theme_key": "光模块/CPO",
            "root_id": "C0CD",
            "root_name": "共封装光学(CPO)",
            "branch_count": 1,
            "leaf_count": 1,
            "tree": {
                "id": "C0CD",
                "name": "共封装光学(CPO)",
                "node_type": "branch",
                "block_type": "hot-theme",
                "children": [
                    {
                        "id": "B097",
                        "name": "光模块",
                        "node_type": "leaf",
                        "block_type": "concept-subdivision",
                        "stock_count": 2,
                    },
                ],
            },
        }

    def fake_theme_stocks(**kwargs):
        assert kwargs.get("block_code") == "B097"
        assert kwargs.get("scope") == "leaf"
        return {
            "ok": True,
            "action": "stocks",
            "block_name": "光模块",
            "count": 2,
            "stocks": [
                {"market_id": "17", "code": "600103", "symbol": "600103.SH", "name": "青山纸业"},
                {"market_id": "33", "code": "000001", "symbol": "000001.SZ", "name": "平安银行"},
            ],
        }

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: "/tmp/ths")
    monkeypatch.setattr("ths_block.linker.fetch_theme_list", fake_theme_list)
    monkeypatch.setattr("ths_block.linker.fetch_theme_tree", fake_theme_tree)
    monkeypatch.setattr("ths_block.linker.fetch_theme_stocks", fake_theme_stocks)

    snap = block_service.refresh_kind(kind="theme", force=True)
    entry = snap["kinds"]["theme"]
    assert entry["tree_mode"] == "tree"
    assert entry["root_id"] == "__theme_root__"
    assert entry.get("fetched_date")
    assert any(r["id"] == "C0CD" and r["node_type"] == "branch" for r in entry["rows"])
    leaf = next(r for r in entry["rows"] if r["id"] == "B097")
    assert leaf["node_type"] == "leaf"
    assert leaf["theme_key"] == "光模块/CPO"
    assert leaf["root_id"] == "C0CD"
    assert leaf["parent_id"] == "C0CD"

    detail = block_service.get_block_stocks(kind="theme", block_id="B097")
    assert detail["count"] == 2
    assert detail["stocks"][0]["code"] == "600103"
    assert detail["stocks"][0]["market"] == "17"
    assert detail["stocks"][0]["name"] == "青山纸业"


def test_theme_daily_limit_reuses_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """热点主题非 force 时复用当日落盘，不重复请求 ths-linker。"""
    from ths_block import theme_daily

    cache_dir = tmp_path / "ths_theme"
    cache_dir.mkdir()
    monkeypatch.setattr(theme_daily, "_CACHE_DIR", str(cache_dir))
    theme_daily.clear_mem()
    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})

    calls = {"list": 0}

    def fake_theme_list(**_kw):
        calls["list"] += 1
        return {
            "ok": True,
            "action": "list",
            "source": "local",
            "blocks": {
                "C0CD": {"name": "共封装光学(CPO)", "block_type": "hot-theme"},
            },
        }

    def fake_theme_tree(**_kw):
        return {
            "ok": True,
            "action": "tree",
            "source": "local",
            "theme_key": "光模块/CPO",
            "root_id": "C0CD",
            "root_name": "共封装光学(CPO)",
            "branch_count": 1,
            "leaf_count": 1,
            "tree": {
                "id": "C0CD",
                "name": "共封装光学(CPO)",
                "node_type": "branch",
                "block_type": "hot-theme",
                "children": [
                    {"id": "B097", "name": "光模块", "node_type": "leaf", "block_type": "concept-subdivision"},
                ],
            },
        }

    monkeypatch.setattr(block_service, "_resolve_ths_dir", lambda explicit=None: "/tmp/ths")
    monkeypatch.setattr("ths_block.linker.fetch_theme_list", fake_theme_list)
    monkeypatch.setattr("ths_block.linker.fetch_theme_tree", fake_theme_tree)

    block_service.refresh_kind(kind="theme", force=True)
    assert calls["list"] >= 1
    first_calls = calls["list"]

    block_cache.set_snapshot({"updated_at": None, "kinds": {}, "empty": True})
    theme_daily.clear_mem()  # 仅清内存，落盘仍在
    snap2 = block_service.refresh_kind(kind="theme", force=False)
    assert calls["list"] == first_calls
    assert snap2["kinds"]["theme"]["rows"]
    assert snap2["kinds"]["theme"].get("from_cache") is True

    block_service.refresh_kind(kind="theme", force=True)
    assert calls["list"] > first_calls

