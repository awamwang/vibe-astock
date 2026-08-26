"""消息分析模块测试。"""

from __future__ import annotations

import json
import os

import pytest

from vr.message import cls, parser, store, xgb
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


def test_get_raws_for_analyzed(msg_db):
    items = [{"title": "原始标题", "content": "原始正文内容"}]
    payload = IngestPayload(format="structured", source_id="paste", items=items)
    drafts = parser.parse_ingest(payload)
    inserted = store.insert_raw_batch(drafts, path=msg_db)
    an = store.upsert_analyzed_from_raw(inserted[0], path=msg_db)
    raws = store.get_raws_for_analyzed(an.id, path=msg_db)
    assert len(raws) == 1
    assert raws[0].content == "原始正文内容"
    assert raws[0].id == inserted[0].id


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
    assert draft.content == "摘要"
    assert draft.keywords == []
    assert draft.meta.get("subj_ids") == ["9"]
    assert any(t.kind == "stock" and t.code == "600519" for t in draft.targets)
    assert any(t.kind == "sector" and t.name == "白酒" and t.code == "bk1" for t in draft.targets)


def test_xgb_body_fallback_title():
    item = {
        "Id": "99",
        "Title": "夜盘期货开盘，乙二醇跌近4%",
        "Summary": "",
        "Content": "",
        "CreatedAtInSec": 1700000000,
    }
    draft = xgb.map_xgb_item(item)
    assert draft.content == "夜盘期货开盘，乙二醇跌近4%"


def test_xgb_targets_sync_to_analyzed(msg_db):
    item = {
        "Id": "888",
        "Title": "板块异动",
        "AllStocks": [{"Name": "海南橡胶", "Symbol": "601118.SH"}],
        "BkjInfoArr": [{"Id": "123", "Name": "农业"}],
        "CreatedAtInSec": 1700000000,
    }
    draft = xgb.map_xgb_item(item)
    raw = store.insert_raw_batch([draft], path=msg_db)[0]
    store.upsert_analyzed_from_raw(raw, patch={"targets": [t.model_dump() for t in draft.targets]}, path=msg_db)
    rows, _ = store.list_analyzed(store.ListQuery(source="xgb_msgs"), path=msg_db)
    assert len(rows) == 1
    kinds = {t.kind for t in rows[0].targets}
    assert "stock" in kinds and "sector" in kinds
    stock = next(t for t in rows[0].targets if t.kind == "stock")
    assert stock.code == "601118" and stock.name == "海南橡胶"


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


def test_multi_filter_analyzed(msg_db):
    def _insert(title: str, source_id: str, impact: str, effect: str):
        d = RawMessageDraft(
            draft_key=f"d-{title}",
            source_id=source_id,
            source_label=source_id,
            content=title,
            title=title,
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        store.upsert_analyzed_from_raw(
            raw,
            patch={"impact_level": impact, "effect_status": effect},
            path=msg_db,
        )

    _insert("高影响A", "paste", "high", "not_erupted")
    _insert("中影响B", "paste", "medium", "early_hype")
    _insert("选股宝C", "xgb_msgs", "high", "ongoing_hype")

    rows, total = store.list_analyzed(
        store.ListQuery(impact_level="high,medium"),
        path=msg_db,
    )
    assert total == 3
    titles = {r.title for r in rows}
    assert titles == {"高影响A", "中影响B", "选股宝C"}

    rows, total = store.list_analyzed(
        store.ListQuery(impact_level="medium"),
        path=msg_db,
    )
    assert total == 1
    assert rows[0].title == "中影响B"

    rows2, total2 = store.list_analyzed(
        store.ListQuery(source="paste,xgb_msgs", effect_status="not_erupted,ongoing_hype"),
        path=msg_db,
    )
    assert total2 == 2
    titles2 = {r.title for r in rows2}
    assert titles2 == {"高影响A", "选股宝C"}


def test_merge_drafts():
    drafts = [
        RawMessageDraft(draft_key="a", source_id="paste", content="段1", title="段1"),
        RawMessageDraft(draft_key="b", source_id="paste", content="段2", title="段2"),
    ]
    merged = parser.merge_drafts(drafts, [0, 1])
    assert "段1" in merged.content and "段2" in merged.content


def test_follow_keywords_match_and_filter(msg_db, tmp_path, monkeypatch):
    from duanxian import message_follow_keywords as mfk

    cfg = tmp_path / "message_follow_keywords.json"
    monkeypatch.setattr(mfk, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(mfk, "_KEYWORDS", None)
    mfk.save_keywords(["光通信", "算力"])

    def _insert(title: str, summary: str = ""):
        d = RawMessageDraft(
            draft_key=f"d-{title}",
            source_id="paste",
            source_label="粘贴",
            content=title,
            title=title,
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        store.upsert_analyzed_from_raw(
            raw,
            patch={"summary": summary or title},
            path=msg_db,
        )

    _insert("光通信板块走强")
    _insert("普通新闻", "与关注词无关")

    rows, total = store.list_analyzed(store.ListQuery(followed="yes"), path=msg_db)
    assert total == 1
    assert rows[0].followed is True
    assert "光通信" in rows[0].matched_follow_keywords

    rows_no, total_no = store.list_analyzed(store.ListQuery(followed="no"), path=msg_db)
    assert total_no == 1
    assert rows_no[0].followed is False


def test_cls_map():
    item = {
        "id": 2465425,
        "title": "蒙牛乳业：上半年净利润23.7亿元",
        "content": "【蒙牛乳业：上半年净利润23.7亿元】财联社8月26日电，…",
        "ctime": 1787752579,
        "level": "A",
        "subjects": [{"subject_name": "食品饮料"}, {"subject_name": "港股动态"}],
        "shareurl": None,
    }
    draft = cls.map_cls_item(item)
    assert draft.external_ref == "2465425"
    assert draft.source_id == "cls_telegraph"
    assert "highlight" in draft.marks
    assert draft.keywords == ["食品饮料", "港股动态"]
    assert cls.level_to_impact("A") == "high"
    assert cls.level_to_impact("C") == "low"


def test_follow_impact_boost(msg_db, tmp_path, monkeypatch):
    from duanxian import message_follow_keywords as mfk
    from vr.message import follow

    cfg = tmp_path / "message_follow_keywords.json"
    monkeypatch.setattr(mfk, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(mfk, "_KEYWORDS", None)
    mfk.save_keywords(["半导体"])

    d = RawMessageDraft(
        draft_key="d-boost",
        source_id="cls_telegraph",
        source_label="财联社",
        content="半导体板块走强",
        title="半导体板块走强",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    store.upsert_analyzed_from_raw(
        raw,
        patch={"impact_level": "medium", "summary": "半导体板块走强"},
        path=msg_db,
    )
    rows, _ = store.list_analyzed(store.ListQuery(source="cls_telegraph"), path=msg_db)
    assert len(rows) == 1
    assert rows[0].followed is True
    assert rows[0].impact_level == "high"
    assert follow.boost_impact_level("critical") == "critical"


def test_cls_fetch_incremental(msg_db, monkeypatch):
    batch1 = [
        {
            "id": 100,
            "title": "第一条",
            "content": "第一条内容",
            "ctime": 1700000000,
            "level": "C",
            "subjects": [],
        },
        {
            "id": 101,
            "title": "第二条",
            "content": "第二条内容",
            "ctime": 1700000060,
            "level": "B",
            "subjects": [{"subject_name": "测试题材"}],
        },
    ]
    batch2 = [
        {
            "id": 102,
            "title": "第三条",
            "content": "第三条内容",
            "ctime": 1700000120,
            "level": "A",
            "subjects": [],
        },
        *batch1,
    ]

    calls = {"n": 0}

    def fake_roll():
        calls["n"] += 1
        return batch1 if calls["n"] == 1 else batch2

    monkeypatch.setattr(cls, "_fetch_roll_data", fake_roll)
    r1 = cls.fetch_telegraph(path=msg_db)
    assert r1["inserted"] == 2
    assert r1["synced"] == 2
    assert r1["tail_mark"] == "101"

    r2 = cls.fetch_telegraph(path=msg_db)
    assert r2["inserted"] == 1
    assert r2["new_candidates"] == 1
    assert r2["tail_mark"] == "102"

    rows, total = store.list_analyzed(store.ListQuery(source="cls_telegraph"), path=msg_db)
    assert total == 3

