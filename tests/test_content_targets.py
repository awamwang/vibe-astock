"""消息正文标的解析与去重。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VR = ROOT / "vr"
if str(VR) not in sys.path:
    sys.path.insert(0, str(VR))

from message.content_targets import (  # noqa: E402
    fill_target_stock_codes,
    merge_targets,
    resolve_content_targets,
)
from message.schemas import ImpactTarget  # noqa: E402
import stock_universe as su  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_universe(monkeypatch):
    monkeypatch.setattr(su, "_by_code", {})
    monkeypatch.setattr(su, "_name_to_code", {})
    monkeypatch.setattr(su, "_loaded", False)
    monkeypatch.setattr(su, "_meta", su.LoadMeta(ok=False))
    items = [
        su.StockItem(code="600000", name="浦发银行", market="SH", types=("主板",)),
        su.StockItem(code="000061", name="农产品", market="SZ", types=("主板",)),
        su.StockItem(code="000049", name="德赛电池", market="SZ", types=("主板",)),
    ]
    su._apply_items(items, "cache", tried=("cache",), updated_at="2026-08-27 12:00:00", from_cache=True)


def test_merge_dedupes_name_with_embedded_block_code():
    merged = merge_targets(
        [
            ImpactTarget(kind="sector", code="61", name="上海"),
            ImpactTarget(kind="sector", code="49", name="北京"),
        ],
        [
            ImpactTarget(kind="sector", code=None, name="上海(61)"),
            ImpactTarget(kind="sector", code=None, name="北京（49）"),
            ImpactTarget(kind="sector", code=None, name="广州"),
        ],
    )
    names = [(t.kind, t.name, t.code) for t in merged]
    assert names == [
        ("sector", "上海", "61"),
        ("sector", "北京", "49"),
        ("sector", "广州", None),
    ]


def test_merge_stock_requires_six_digit_code():
    merged = merge_targets(
        [
            ImpactTarget(kind="stock", code="61", name="上海"),
            ImpactTarget(kind="stock", code="600000", name="浦发银行"),
        ]
    )
    assert len(merged) == 2
    assert merged[0].code is None and merged[0].name == "上海"
    assert merged[1].code == "600000"


def test_fill_keeps_sector_short_id_but_not_as_stock_code():
    rows = fill_target_stock_codes(
        [
            {"kind": "sector", "code": "61", "name": "上海"},
            {"kind": "stock", "code": "61", "name": "误标"},
            {"kind": "stock", "code": None, "name": "浦发银行"},
        ]
    )
    assert rows[0] == {"kind": "sector", "code": "61", "name": "上海"}
    assert rows[1]["kind"] == "stock" and rows[1]["code"] is None
    assert rows[2] == {"kind": "stock", "code": "600000", "name": "浦发银行"}


def test_resolve_content_targets_exact_stock_name_only(monkeypatch):
    text = "8月300城住宅用地出让金1457亿元 同比增长37%"
    # 正文无个股名时不应扫出农产品/德赛电池
    out = resolve_content_targets(text)
    stock_names = {t.name for t in out if t.kind == "stock"}
    assert "农产品" not in stock_names
    assert "德赛电池" not in stock_names

    hit = resolve_content_targets("盘中浦发银行走强")
    assert any(t.kind == "stock" and t.code == "600000" for t in hit)
