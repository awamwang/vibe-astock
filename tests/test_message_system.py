"""消息分析模块测试。"""

from __future__ import annotations

import json
import os

import pytest

from vr.message import parser, store, xgb
from vr.message.schemas import IngestPayload, RawMessageDraft


@pytest.fixture
def msg_db(tmp_path):
    path = str(tmp_path / "messages.db")
    store.init_db(path)
    return path


def test_split_plain_blank(msg_db):
    payload = IngestPayload(format="plain", source_id="paste", text="第一条\n\n第二条")
    drafts = parser.parse_ingest(payload)
    assert len(drafts) == 2
    assert "第一条" in drafts[0].content
    assert "第二条" in drafts[1].content


def test_structured_ingest(msg_db):
    items = [
        {
            "title": "测试标题",
            "content": "正文内容",
            "url": "https://example.com/a",
            "keywords": ["半导体"],
            "marks": ["highlight"],
        }
    ]
    payload = IngestPayload(format="structured", source_id="structured", items=items)
    drafts = parser.parse_ingest(payload)
    assert len(drafts) == 1
    assert drafts[0].title == "测试标题"
    assert drafts[0].keywords == ["半导体"]
    assert drafts[0].marks == ["highlight"]
    inserted = store.insert_raw_batch(drafts, path=msg_db)
    assert len(inserted) == 1
    rows, total = store.list_raw(store.ListQuery(), path=msg_db)
    assert total == 1
    assert rows[0].title == "测试标题"


def test_calendar_effective(msg_db):
    items = [
        {
            "title": "美联储议息",
            "content": "公布利率决议",
            "effective_at": "2026-09-17 02:00:00",
        }
    ]
    payload = IngestPayload(format="calendar", items=items)
    drafts = parser.parse_ingest(payload)
    assert drafts[0].effective_mode == "scheduled"
    assert drafts[0].effective_at == "2026-09-17 02:00:00"
    inserted = store.insert_raw_batch(drafts, path=msg_db)
    an = store.upsert_analyzed_from_raw(
        inserted[0],
        patch={"effective_mode": "scheduled", "effective_at": drafts[0].effective_at},
        path=msg_db,
    )
    assert an.effective_mode == "scheduled"
    assert an.effective_at == "2026-09-17 02:00:00"


def test_xgb_map():
    item = {
        "Id": "12345",
        "Title": "某股涨停",
        "Summary": "摘要",
        "AllStocks": [{"Name": "测试股", "Symbol": "600519.SH"}],
        "BkjInfoArr": [{"Id": "bk1", "Name": "白酒"}],
        "CreatedAtInSec": 1700000000,
        "SubjIds": ["9"],
    }
    draft = xgb.map_xgb_item(item)
    assert draft.external_ref == "12345"
    assert draft.title == "某股涨停"
    assert any(t.code == "600519" for t in draft.targets)
    assert any(t.name == "白酒" for t in draft.targets)


def test_dedup_external_ref(msg_db):
    d = RawMessageDraft(
        draft_key="d1",
        source_id="xgb_msgs",
        source_label="选股宝",
        content="同一条",
        title="同一条",
        external_ref="999",
    )
    first = store.insert_raw_batch([d], path=msg_db)
    second = store.insert_raw_batch([d], path=msg_db)
    assert len(first) == 1
    assert len(second) == 0


def test_search_analyzed(msg_db):
    d = RawMessageDraft(
        draft_key="d2",
        source_id="paste",
        source_label="粘贴",
        content="低空经济政策出台",
        title="低空经济",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    store.upsert_analyzed_from_raw(
        raw,
        patch={"summary": "低空经济政策", "keywords": ["低空"]},
        path=msg_db,
    )
    rows, total = store.list_analyzed(
        store.ListQuery(q="低空"),
        path=msg_db,
    )
    assert total >= 1
    assert any("低空" in r.title or "低空" in r.summary for r in rows)


def test_merge_drafts():
    drafts = [
        RawMessageDraft(draft_key="a", source_id="paste", content="段1", title="段1"),
        RawMessageDraft(draft_key="b", source_id="paste", content="段2", title="段2"),
    ]
    merged = parser.merge_drafts(drafts, [0, 1])
    assert "段1" in merged.content and "段2" in merged.content
