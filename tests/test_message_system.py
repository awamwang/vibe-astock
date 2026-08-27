"""消息分析模块测试。"""

from __future__ import annotations

import json
import os

import pytest

from vr.message import archive, cls, parser, store, xgb
from vr.message.schemas import IngestPayload, RawMessageDraft


@pytest.fixture
def msg_db(tmp_path):
    path = str(tmp_path / "messages.db")
    store.init_db(path)
    return path


def test_split_plain_blank(msg_db):
    payload = IngestPayload(format="plain", source_id="manual", text="第一条\n\n第二条")
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
    payload = IngestPayload(format="structured", source_id="manual", items=items)
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


def test_calendar_v4_json_import(msg_db, monkeypatch):
    monkeypatch.setattr(parser, "_now_str", lambda: "2026-08-26 12:00:00")
    doc = {
        "meta": {
            "title": "2026年9月财经大事",
            "month": 9,
            "year": 2026,
            "source": {"name": "同花顺", "brand_display": "同花顺财经日历"},
            "disclaimer": "仅供参考",
            "total_events": 2,
        },
        "legend": [
            {
                "key": "must_watch",
                "label": "必看大事",
                "icon_hint": "red",
                "color_hint": "#ff0000",
            }
        ],
        "events": [
            {
                "id": "evt-001",
                "startTime": 1790697600000,
                "title": "美联储议息",
                "importanceLevel": 4,
                "category": "必看大事",
                "targets": [
                    {"type": "sector", "name": "银行", "code": "bk0475"},
                    {"type": "stock", "name": "招商银行", "code": "600036"},
                ],
            },
            {
                "id": "evt-002",
                "startTime": 1790784000000,
                "title": "消费电子展",
                "importanceLevel": 2,
                "category": "行业会展",
                "targets": [{"type": "subject", "name": "消费电子", "code": ""}],
            },
        ],
    }
    payload = IngestPayload(format="calendar", text=json.dumps(doc, ensure_ascii=False))
    drafts = parser.parse_ingest(payload)
    assert len(drafts) == 2
    assert drafts[0].title == "美联储议息"
    assert drafts[0].effective_mode == "scheduled"
    assert drafts[0].effective_at == "2026-09-30 00:00:00"
    assert drafts[0].produced_at == "2026-08-26 12:00:00"
    assert drafts[0].produced_at != drafts[0].effective_at
    assert drafts[0].external_ref == "evt-001"
    assert drafts[0].keywords == ["必看大事"]
    assert "must_watch" in drafts[0].marks
    assert "flame" in drafts[0].marks
    assert drafts[0].content == "美联储议息"
    assert "类别：" not in drafts[0].content
    assert drafts[0].meta.get("impact_level") == "high"
    assert drafts[1].meta.get("impact_level") == "low"
    assert any(t.kind == "sector" and t.name == "银行" for t in drafts[0].targets)
    assert any(t.kind == "stock" and t.code == "600036" for t in drafts[0].targets)
    assert drafts[1].title == "消费电子展"
    assert any(t.kind == "theme" and t.name == "消费电子" for t in drafts[1].targets)
    inserted = store.insert_raw_batch(drafts, path=msg_db)
    assert len(inserted) == 2
    an = store.upsert_analyzed_from_raw(
        inserted[0],
        patch={
            "effective_mode": "scheduled",
            "effective_at": drafts[0].effective_at,
            "impact_level": drafts[0].meta["impact_level"],
        },
        path=msg_db,
    )
    assert an.impact_level == "high"


@pytest.mark.parametrize(
    ("level", "impact"),
    [(1, "noise"), (2, "low"), (3, "medium"), (4, "high"), (5, "critical")],
)
def test_importance_to_impact(level, impact):
    assert parser.importance_to_impact(level) == impact


def test_get_raws_for_analyzed(msg_db):
    items = [{"title": "原始标题", "content": "原始正文内容"}]
    payload = IngestPayload(format="structured", source_id="manual", items=items)
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
    import time

    item = {
        "Id": "888",
        "Title": "板块异动",
        "AllStocks": [{"Name": "海南橡胶", "Symbol": "601118.SH"}],
        "BkjInfoArr": [{"Id": "123", "Name": "农业"}],
        "CreatedAtInSec": int(time.time()) - 60,
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
        source_id="manual",
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

    _insert("高影响A", "manual", "high", "not_erupted")
    _insert("中影响B", "manual", "medium", "pending_verify")
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
        store.ListQuery(source="manual,xgb_msgs", effect_status="not_erupted,ongoing_hype"),
        path=msg_db,
    )
    assert total2 == 2
    titles2 = {r.title for r in rows2}
    assert titles2 == {"高影响A", "选股宝C"}


def test_merge_drafts():
    drafts = [
        RawMessageDraft(draft_key="a", source_id="manual", content="段1", title="段1"),
        RawMessageDraft(draft_key="b", source_id="manual", content="段2", title="段2"),
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
            source_id="manual",
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
    import time

    base = int(time.time()) - 120
    batch1 = [
        {
            "id": 100,
            "title": "第一条",
            "content": "第一条内容",
            "ctime": base,
            "level": "C",
            "subjects": [],
        },
        {
            "id": 101,
            "title": "第二条",
            "content": "第二条内容",
            "ctime": base + 60,
            "level": "B",
            "subjects": [{"subject_name": "测试题材"}],
        },
    ]
    batch2 = [
        {
            "id": 102,
            "title": "第三条",
            "content": "第三条内容",
            "ctime": base + 120,
            "level": "A",
            "subjects": [],
        },
        *batch1,
    ]

    calls = {"n": 0}

    def fake_roll(last_id, **_kw):
        calls["n"] += 1
        items = batch2 if calls["n"] > 1 else batch1
        new_items = [i for i in items if int(i["id"]) > last_id]
        return new_items, 1

    monkeypatch.setattr(cls, "fetch_roll_since_id", fake_roll)
    monkeypatch.setattr(
        archive,
        "archive_immediate_expired",
        lambda **_: {"archived": 0, "deleted_analyzed": 0, "cutoff": ""},
    )
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


def test_cls_fetch_roll_pagination(monkeypatch):
    page1 = [{"id": 300, "ctime": 1000}, {"id": 250, "ctime": 900}]
    page2 = [{"id": 200, "ctime": 800}, {"id": 150, "ctime": 700}]
    calls: list[int] = []

    def fake_page(*, last_time, rn, timeout=20):
        calls.append(last_time)
        if len(calls) == 1:
            return page1
        if len(calls) == 2:
            return page2
        return []

    monkeypatch.setattr(cls, "_fetch_roll_page", fake_page)
    items, pages = cls.fetch_roll_since_id(180, page_size=2, max_pages=5)
    assert pages == 2
    assert [i["id"] for i in items] == [200, 250, 300]


def test_cls_fetch_roll_partial_page_continues(monkeypatch):
    """API 返回不满页但仍有新消息时，应继续翻页而非提前停止。"""
    page1 = [{"id": 300, "ctime": 1000}, {"id": 250, "ctime": 900}]
    page2 = [{"id": 200, "ctime": 800}]
    calls: list[int] = []

    def fake_page(*, last_time, rn, timeout=20):
        calls.append(last_time)
        if len(calls) == 1:
            return page1
        if len(calls) == 2:
            return page2
        return []

    monkeypatch.setattr(cls, "_fetch_roll_page", fake_page)
    items, pages = cls.fetch_roll_since_id(180, page_size=3, max_pages=5)
    assert pages == 3
    assert [i["id"] for i in items] == [200, 250, 300]


def test_cls_fetch_roll_since_ctime(monkeypatch):
    page1 = [
        {"id": 300, "ctime": 2000},
        {"id": 250, "ctime": 1500},
    ]
    page2 = [
        {"id": 200, "ctime": 800},
        {"id": 150, "ctime": 500},
    ]
    calls: list[int] = []

    def fake_page(*, last_time, rn, timeout=20):
        calls.append(last_time)
        if len(calls) == 1:
            return page1
        if len(calls) == 2:
            return page2
        return []

    monkeypatch.setattr(cls, "_fetch_roll_page", fake_page)
    items, pages = cls.fetch_roll_since_ctime(1000, page_size=2, max_pages=5)
    assert pages == 2
    assert [i["id"] for i in items] == [250, 300]


def test_cls_fetch_telegraph_backfill_today(msg_db, monkeypatch):
    inc = [{"id": 102, "title": "新", "content": "新内容", "ctime": 2000, "level": "B", "subjects": []}]
    backfill = [{"id": 101, "title": "漏", "content": "漏掉", "ctime": 1500, "level": "C", "subjects": []}]

    monkeypatch.setattr(cls, "fetch_roll_since_id", lambda last_id, **_kw: (inc, 1))
    monkeypatch.setattr(cls, "fetch_roll_since_ctime", lambda min_ctime, **_kw: (backfill, 1))
    monkeypatch.setattr(
        archive,
        "archive_immediate_expired",
        lambda **_: {"archived": 0, "deleted_analyzed": 0, "cutoff": ""},
    )
    store.set_poll_state("cls_telegraph", tail_mark="100", path=msg_db)

    r = cls.fetch_telegraph(path=msg_db, backfill_today=True)
    assert r["fetched"] == 2
    assert r["inserted"] == 2
    assert r["tail_mark"] == "102"

    rows, total = store.list_analyzed(store.ListQuery(source="cls_telegraph"), path=msg_db)
    assert total == 2
    titles = {row.title for row in rows}
    assert titles == {"新", "漏"}


def test_archive_immediate_expired(msg_db, tmp_path):
    arc_path = str(tmp_path / "archive.db")
    old_time = "2020-01-01 10:00:00"
    recent_time = store._now()

    d_old = RawMessageDraft(
        draft_key="old",
        source_id="manual",
        source_label="粘贴",
        content="旧消息",
        title="旧消息",
        produced_at=old_time,
    )
    d_new = RawMessageDraft(
        draft_key="new",
        source_id="manual",
        source_label="粘贴",
        content="新消息",
        title="新消息",
        produced_at=recent_time,
    )
    raw_old = store.insert_raw_batch([d_old], path=msg_db)[0]
    raw_new = store.insert_raw_batch([d_new], path=msg_db)[0]
    store.upsert_analyzed_from_raw(raw_old, patch={"effective_mode": "immediate"}, path=msg_db)
    store.upsert_analyzed_from_raw(
        raw_new,
        patch={"effective_mode": "scheduled", "effective_at": "2099-01-01 09:00:00"},
        path=msg_db,
    )

    stats = archive.archive_immediate_expired(days=7, main_path=msg_db, archive_path=arc_path)
    assert stats["archived"] == 1
    assert stats["deleted_analyzed"] == 1

    active, active_total = store.list_analyzed(store.ListQuery(), path=msg_db)
    assert active_total == 1
    assert active[0].title == "新消息"

    archived_rows, archived_total = archive.list_raw_archive(store.ListQuery(), path=arc_path)
    assert archived_total == 1
    assert archived_rows[0].title == "旧消息"
    assert archived_rows[0].content == "旧消息"


def test_list_analyzed_pagination_and_sort(msg_db):
    def _insert(title: str, impact: str, effect: str):
        d = RawMessageDraft(
            draft_key=f"pg-{title}",
            source_id="manual",
            source_label="粘贴",
            content=title,
            title=title,
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        store.upsert_analyzed_from_raw(
            raw,
            patch={"impact_level": impact, "effect_status": effect},
            path=msg_db,
        )

    for i in range(5):
        _insert(f"消息{i}", "medium", "not_erupted" if i % 2 == 0 else "pending_verify")

    page1, total = store.list_analyzed(
        store.ListQuery(limit=2, offset=0, sort="title", order="asc"),
        path=msg_db,
    )
    assert total == 5
    assert len(page1) == 2

    page3, _ = store.list_analyzed(
        store.ListQuery(limit=2, offset=4, sort="title", order="asc"),
        path=msg_db,
    )
    assert len(page3) == 1

    by_effect, _ = store.list_analyzed(
        store.ListQuery(sort="effect_status", order="asc"),
        path=msg_db,
    )
    effects = [r.effect_status for r in by_effect]
    assert effects == sorted(effects)


def test_favorited_batch_and_filter(msg_db):
    d = RawMessageDraft(
        draft_key="fav1",
        source_id="manual",
        source_label="粘贴",
        content="收藏测试",
        title="收藏测试",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    an = store.upsert_analyzed_from_raw(raw, path=msg_db)
    assert an.favorited is False

    n = store.set_favorited_batch([an.id], True, path=msg_db)
    assert n == 1
    got = store.get_analyzed(an.id, path=msg_db)
    assert got is not None
    assert got.favorited is True

    yes_rows, yes_total = store.list_analyzed(
        store.ListQuery(favorited="yes"),
        path=msg_db,
    )
    assert yes_total == 1
    assert yes_rows[0].id == an.id

    no_rows, no_total = store.list_analyzed(
        store.ListQuery(favorited="no"),
        path=msg_db,
    )
    assert no_total == 0
    assert no_rows == []


def test_delete_analyzed_batch(msg_db):
    ids: list[str] = []
    for i in range(2):
        d = RawMessageDraft(
            draft_key=f"del{i}",
            source_id="manual",
            source_label="粘贴",
            content=f"删除测试{i}",
            title=f"删除测试{i}",
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        an = store.upsert_analyzed_from_raw(raw, path=msg_db)
        ids.append(an.id)

    deleted = store.delete_analyzed_batch([ids[0]], path=msg_db)
    assert deleted == 1
    assert store.get_analyzed(ids[0], path=msg_db) is None
    assert store.get_analyzed(ids[1], path=msg_db) is not None
    assert store.get_raws_for_analyzed(ids[0], path=msg_db) == []

    rows, total = store.list_analyzed(store.ListQuery(), path=msg_db)
    assert total == 1
    assert rows[0].id == ids[1]


def test_end_at_update_and_clear(msg_db):
    from vr.message.dates import effective_end_at, has_explicit_end_at
    from vr.message.schemas import AnalyzedMessage

    d = RawMessageDraft(
        draft_key="end1",
        source_id="manual",
        source_label="手动",
        content="结束时间测试",
        title="结束时间测试",
        produced_at="2026-08-01 10:00:00",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    an = store.upsert_analyzed_from_raw(raw, path=msg_db)
    assert an.end_at is None
    assert effective_end_at(an, default_days=5) == "2026-08-06 10:00:00"

    updated = store.update_analyzed(
        an.id,
        {"end_at": "2026-08-20 18:00:00"},
        path=msg_db,
    )
    assert updated is not None
    assert updated.end_at == "2026-08-20 18:00:00"
    assert has_explicit_end_at(updated)

    cleared = store.update_analyzed(an.id, {"end_at": None}, path=msg_db)
    assert cleared is not None
    assert cleared.end_at is None
    assert effective_end_at(cleared, default_days=3) == "2026-08-04 10:00:00"


def test_effective_end_at_scheduled(msg_db):
    from vr.message.dates import effective_at_dt, effective_end_at
    from vr.message.schemas import AnalyzedMessage

    msg = AnalyzedMessage(
        id="x",
        source_id="manual",
        produced_at="2026-08-01 10:00:00",
        effective_mode="scheduled",
        effective_at="2026-08-05 09:00:00",
    )
    assert effective_at_dt(msg) == "2026-08-05 09:00:00"
    assert effective_end_at(msg, default_days=5) == "2026-08-10 09:00:00"

