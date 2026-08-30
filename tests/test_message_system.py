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


def test_article_ingest_keeps_whole_text(msg_db):
    text = "白酒景气跟踪\n\n贵州茅台份额提升。\n\n行业集中度上行。"
    payload = IngestPayload(format="article", source_id="article", text=text)
    drafts = parser.parse_ingest(payload)
    assert len(drafts) == 1
    assert drafts[0].source_id == "article"
    assert drafts[0].source_label == "研报文章"
    assert drafts[0].content == text
    assert drafts[0].title.startswith("白酒景气跟踪")
    assert drafts[0].meta.get("format") == "article"


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


def test_list_analyzed_match_current_stock(msg_db, monkeypatch):
    from duanxian import current_stock as cs

    def _make_msg(title: str, code: str):
        d = RawMessageDraft(
            draft_key=f"stk-{code}-{title}",
            source_id="manual",
            source_label="手动",
            content=title,
            title=title,
            targets=[{"kind": "stock", "code": code, "name": f"股{code}"}],
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        return store.upsert_analyzed_from_raw(
            raw,
            patch={"targets": [t.model_dump() for t in d.targets]},
            path=msg_db,
        )

    _make_msg("茅台消息", "600519")
    _make_msg("平安消息", "000001")

    monkeypatch.setattr(cs, "get_current", lambda: None)
    empty, empty_total = store.list_analyzed(
        store.ListQuery(match_current_stock="yes"),
        path=msg_db,
    )
    assert empty_total == 0
    assert empty == []

    monkeypatch.setattr(
        cs,
        "get_current",
        lambda: cs.CurrentStock(
            code="600519",
            plugin_id="test",
            source="test",
            prev=None,
            updated_at="2026-08-27 10:00:00",
        ),
    )
    monkeypatch.setattr(
        "vr.message.current_stock_match.resolve_stock_name",
        lambda code: "贵州茅台" if code == "600519" else "",
    )
    matched, matched_total = store.list_analyzed(
        store.ListQuery(match_current_stock="yes"),
        path=msg_db,
    )
    assert matched_total == 1
    assert matched[0].title == "茅台消息"


def test_list_analyzed_match_current_stock_via_content(msg_db, monkeypatch):
    from duanxian import current_stock as cs

    d = RawMessageDraft(
        draft_key="content-mt",
        source_id="manual",
        source_label="手动",
        content="市场传闻贵州茅台提价",
        title="提价传闻",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    store.upsert_analyzed_from_raw(
        raw,
        patch={
            "summary": "贵州茅台或将提价",
            "detail": "市场传闻贵州茅台提价",
            "targets": [],
        },
        path=msg_db,
    )
    # 无关消息：摘要/内容不含名称、也无标的
    other = RawMessageDraft(
        draft_key="content-other",
        source_id="manual",
        source_label="手动",
        content="大盘震荡",
        title="大盘震荡",
    )
    other_raw = store.insert_raw_batch([other], path=msg_db)[0]
    store.upsert_analyzed_from_raw(other_raw, patch={"targets": []}, path=msg_db)

    monkeypatch.setattr(
        cs,
        "get_current",
        lambda: cs.CurrentStock(
            code="600519",
            plugin_id="test",
            source="test",
            prev=None,
            updated_at="2026-08-27 10:00:00",
        ),
    )
    monkeypatch.setattr(
        "vr.message.current_stock_match.resolve_stock_name",
        lambda code: "贵州茅台" if code == "600519" else "",
    )
    monkeypatch.setattr(
        "vr.ths_block.match.analyzed_ids_with_stock_in_block_targets",
        lambda conn, code: set(),
    )
    monkeypatch.setattr(
        "ths_block.match.analyzed_ids_with_stock_in_block_targets",
        lambda conn, code: set(),
    )

    matched, matched_total = store.list_analyzed(
        store.ListQuery(match_current_stock="yes"),
        path=msg_db,
    )
    assert matched_total == 1
    assert matched[0].title == "提价传闻"


def test_list_analyzed_match_current_stock_sort_priority(msg_db, monkeypatch):
    from duanxian import current_stock as cs

    def _make(title: str, *, produced_at: str, targets=None, summary="", detail=""):
        d = RawMessageDraft(
            draft_key=f"prio-{title}",
            source_id="manual",
            source_label="手动",
            content=detail or title,
            title=title,
            produced_at=produced_at,
        )
        raw = store.insert_raw_batch([d], path=msg_db)[0]
        return store.upsert_analyzed_from_raw(
            raw,
            patch={
                "targets": targets or [],
                "summary": summary,
                "detail": detail or title,
                "produced_at": produced_at,
            },
            path=msg_db,
        )

    # produced_at 故意让板块最新、标的最旧，验证分层排序压过时间倒序
    block_msg = _make(
        "板块命中",
        produced_at="2026-08-27 12:00:00",
        targets=[{"kind": "sector", "name": "华为概念"}],
    )
    content_msg = _make(
        "内容命中",
        produced_at="2026-08-27 11:00:00",
        summary="贵州茅台提价",
        detail="贵州茅台提价传闻",
    )
    target_msg = _make(
        "标的命中",
        produced_at="2026-08-27 10:00:00",
        targets=[{"kind": "stock", "code": "600519", "name": "贵州茅台"}],
    )

    monkeypatch.setattr(
        cs,
        "get_current",
        lambda: cs.CurrentStock(
            code="600519",
            plugin_id="test",
            source="test",
            prev=None,
            updated_at="2026-08-27 10:00:00",
        ),
    )
    monkeypatch.setattr(
        "vr.message.current_stock_match.resolve_stock_name",
        lambda code: "贵州茅台" if code == "600519" else "",
    )

    def _ids_with_stock(conn, code):
        return {block_msg.id} if code == "600519" else set()

    monkeypatch.setattr(
        "vr.ths_block.match.analyzed_ids_with_stock_in_block_targets",
        _ids_with_stock,
    )
    monkeypatch.setattr(
        "ths_block.match.analyzed_ids_with_stock_in_block_targets",
        _ids_with_stock,
    )
    monkeypatch.setattr(
        "vr.ths_block.match.target_name_contains_stock",
        lambda name, code: name == "华为概念" and code == "600519",
    )
    monkeypatch.setattr(
        "ths_block.match.target_name_contains_stock",
        lambda name, code: name == "华为概念" and code == "600519",
    )

    matched, matched_total = store.list_analyzed(
        store.ListQuery(match_current_stock="yes", sort="produced_at", order="desc"),
        path=msg_db,
    )
    assert matched_total == 3
    assert [m.title for m in matched] == ["标的命中", "内容命中", "板块命中"]
    assert {target_msg.id, content_msg.id, block_msg.id} == {m.id for m in matched}


def test_list_analyzed_match_current_stock_via_block(msg_db, monkeypatch):
    from duanxian import current_stock as cs

    d = RawMessageDraft(
        draft_key="blk-hw",
        source_id="manual",
        source_label="手动",
        content="华为产业链利好",
        title="华为产业链利好",
        targets=[{"kind": "sector", "name": "华为概念"}],
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    an = store.upsert_analyzed_from_raw(
        raw,
        patch={"targets": [t.model_dump() for t in d.targets]},
        path=msg_db,
    )

    monkeypatch.setattr(
        cs,
        "get_current",
        lambda: cs.CurrentStock(
            code="600519",
            plugin_id="test",
            source="test",
            prev=None,
            updated_at="2026-08-27 10:00:00",
        ),
    )
    def _ids_with_stock(conn, code):
        return {an.id} if code == "600519" else set()

    def _name_has_stock(name, code):
        return name == "华为概念" and code == "600519"

    # PYTHONPATH 含 vr/ 时 ths_block 与 vr.ths_block 是两套模块，需同时 patch
    monkeypatch.setattr(
        "vr.ths_block.match.analyzed_ids_with_stock_in_block_targets",
        _ids_with_stock,
    )
    monkeypatch.setattr(
        "ths_block.match.analyzed_ids_with_stock_in_block_targets",
        _ids_with_stock,
    )
    monkeypatch.setattr("vr.ths_block.match.target_name_contains_stock", _name_has_stock)
    monkeypatch.setattr("ths_block.match.target_name_contains_stock", _name_has_stock)
    monkeypatch.setattr(
        "vr.message.current_stock_match.resolve_stock_name",
        lambda code: "",
    )

    matched, matched_total = store.list_analyzed(
        store.ListQuery(match_current_stock="yes"),
        path=msg_db,
    )
    assert matched_total == 1
    assert matched[0].title == "华为产业链利好"
    assert matched[0].matched_current_stock_blocks == ["华为概念"]


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
    an = store.upsert_analyzed_from_raw(
        raw,
        patch={"impact_level": "medium", "summary": "半导体板块走强"},
        path=msg_db,
    )
    # 新建导入时工作档升档并落库；初始档保持来源先验
    assert an.followed is True
    assert an.impact_level == "high"
    assert an.initial_impact_level == "medium"
    assert an.impact_manual is False
    rows, _ = store.list_analyzed(store.ListQuery(source="cls_telegraph"), path=msg_db)
    assert len(rows) == 1
    assert rows[0].followed is True
    assert rows[0].impact_level == "high"
    assert rows[0].initial_impact_level == "medium"
    assert follow.boost_impact_level("critical") == "critical"

    # 手动降级：工作档与初始档同步，并打上手动标记；读取不再二次升档
    updated = store.update_analyzed(an.id, {"impact_level": "medium"}, path=msg_db)
    assert updated is not None
    assert updated.impact_level == "medium"
    assert updated.initial_impact_level == "medium"
    assert updated.impact_manual is True
    assert updated.followed is True
    again = store.get_analyzed(an.id, path=msg_db)
    assert again is not None
    assert again.impact_level == "medium"
    assert again.initial_impact_level == "medium"
    assert again.impact_manual is True
    assert again.followed is True

    # AI 改档不得动初始档，且手动标记后不得覆写工作档
    ai_touch = store.update_analyzed(
        an.id,
        {"impact_level": "critical", "analyzed_by": "ai", "summary": "ai"},
        path=msg_db,
    )
    assert ai_touch is not None
    assert ai_touch.impact_level == "medium"
    assert ai_touch.initial_impact_level == "medium"
    assert ai_touch.impact_manual is True



def test_follow_block_impact_boost_shared_with_keywords(msg_db, tmp_path, monkeypatch):
    """关注板块命中升一档；与关注词共用升档条件，不叠加。"""
    from duanxian import message_follow_blocks as mfb
    from duanxian import message_follow_keywords as mfk

    kw_cfg = tmp_path / "message_follow_keywords.json"
    blk_cfg = tmp_path / "message_follow_blocks.json"
    monkeypatch.setattr(mfk, "_CONFIG_PATH", str(kw_cfg))
    monkeypatch.setattr(mfk, "_KEYWORDS", None)
    monkeypatch.setattr(mfb, "_CONFIG_PATH", str(blk_cfg))
    monkeypatch.setattr(mfb, "_BLOCKS", None)
    mfk.save_keywords(["半导体"])
    mfb.save_blocks([{"kind": "conception", "id": "885788", "name": "半导体"}])

    # 仅板块命中（正文不含关注词）
    d1 = RawMessageDraft(
        draft_key="d-blk-only",
        source_id="manual",
        source_label="粘贴",
        content="相关板块异动",
        title="相关板块异动",
    )
    raw1 = store.insert_raw_batch([d1], path=msg_db)[0]
    an1 = store.upsert_analyzed_from_raw(
        raw1,
        patch={
            "impact_level": "medium",
            "summary": "相关板块异动",
            "targets": [{"kind": "sector", "code": "885788", "name": "半导体"}],
        },
        path=msg_db,
    )
    assert an1.followed is True
    assert an1.impact_level == "high"
    assert an1.initial_impact_level == "medium"
    assert "半导体" in an1.matched_follow_blocks
    assert an1.matched_follow_keywords == []

    # 关注词与关注板块同时命中，仍只升一档
    d2 = RawMessageDraft(
        draft_key="d-both",
        source_id="manual",
        source_label="粘贴",
        content="半导体板块走强",
        title="半导体板块走强",
    )
    raw2 = store.insert_raw_batch([d2], path=msg_db)[0]
    an2 = store.upsert_analyzed_from_raw(
        raw2,
        patch={
            "impact_level": "low",
            "summary": "半导体板块走强",
            "targets": [{"kind": "sector", "code": "885788", "name": "半导体"}],
        },
        path=msg_db,
    )
    assert an2.followed is True
    assert an2.impact_level == "medium"
    assert an2.initial_impact_level == "low"
    assert "半导体" in an2.matched_follow_keywords
    assert "半导体" in an2.matched_follow_blocks

    rows_yes, total_yes = store.list_analyzed(store.ListQuery(followed="yes"), path=msg_db)
    assert total_yes == 2
    assert all(r.followed for r in rows_yes)


def test_initial_impact_preserved_from_ai_without_manual(msg_db):
    """未手动指定时，AI 可改工作档，但不可改初始档。"""
    d = RawMessageDraft(
        draft_key="d-init-ai",
        source_id="manual",
        source_label="手动",
        content="常规公告",
        title="常规公告",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    an = store.upsert_analyzed_from_raw(
        raw,
        patch={"impact_level": "low", "summary": "常规公告"},
        path=msg_db,
    )
    assert an.impact_level == "low"
    assert an.initial_impact_level == "low"
    assert an.impact_manual is False

    ai_upd = store.update_analyzed(
        an.id,
        {"impact_level": "high", "analyzed_by": "ai"},
        path=msg_db,
    )
    assert ai_upd is not None
    assert ai_upd.impact_level == "high"
    assert ai_upd.initial_impact_level == "low"
    assert ai_upd.impact_manual is False


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

    rows, total = store.list_analyzed(
        store.ListQuery(source="cls_telegraph", include_history=True),
        path=msg_db,
    )
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
    d_pending = RawMessageDraft(
        draft_key="pending",
        source_id="manual",
        source_label="粘贴",
        content="待验证旧消息",
        title="待验证旧消息",
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
    raw_pending = store.insert_raw_batch([d_pending], path=msg_db)[0]
    raw_new = store.insert_raw_batch([d_new], path=msg_db)[0]
    store.upsert_analyzed_from_raw(raw_old, patch={"effective_mode": "immediate"}, path=msg_db)
    store.upsert_analyzed_from_raw(
        raw_pending,
        patch={"effective_mode": "immediate", "effect_status": "pending_verify"},
        path=msg_db,
    )
    store.upsert_analyzed_from_raw(
        raw_new,
        patch={"effective_mode": "scheduled", "effective_at": "2099-01-01 09:00:00"},
        path=msg_db,
    )

    stats = archive.archive_immediate_expired(days=7, main_path=msg_db, archive_path=arc_path)
    assert stats["archived"] == 1
    assert stats["deleted_analyzed"] == 1

    active, active_total = store.list_analyzed(
        store.ListQuery(include_history=True),
        path=msg_db,
    )
    assert active_total == 2
    titles = {row.title for row in active}
    assert titles == {"新消息", "待验证旧消息"}

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


def test_partial_api_patch_preserves_effective_and_end(msg_db):
    """快捷 PATCH 只改 effect_status 时，不得清空未传入的生效/结束时间。"""
    from pydantic import BaseModel

    class AnalyzedPatchIn(BaseModel):
        effect_status: str | None = None
        effective_at: str | None = None
        end_at: str | None = None
        impact_level: str | None = None

    d = RawMessageDraft(
        draft_key="partial1",
        source_id="manual",
        source_label="手动",
        content="部分更新保时间",
        title="部分更新保时间",
        produced_at="2026-08-01 10:00:00",
    )
    raw = store.insert_raw_batch([d], path=msg_db)[0]
    an = store.upsert_analyzed_from_raw(
        raw,
        patch={
            "effective_mode": "scheduled",
            "effective_at": "2026-08-05 09:00:00",
        },
        path=msg_db,
    )
    an = store.update_analyzed(an.id, {"end_at": "2026-08-20 18:00:00"}, path=msg_db)
    assert an is not None
    assert an.effective_at == "2026-08-05 09:00:00"
    assert an.end_at == "2026-08-20 18:00:00"

    body = AnalyzedPatchIn.model_validate({"effect_status": "pending_verify"})
    # 旧逻辑 model_dump() 会把未传字段变成 None 并误清时间
    buggy = {
        k: v
        for k, v in body.model_dump().items()
        if v is not None or k in ("effective_at", "end_at")
    }
    assert buggy.get("effective_at") is None and buggy.get("end_at") is None

    patch = store.patch_dict_from_api_model(body)
    assert patch == {"effect_status": "pending_verify"}
    updated = store.update_analyzed(an.id, {**patch, "analyzed_by": "human"}, path=msg_db)
    assert updated is not None
    assert updated.effect_status == "pending_verify"
    assert updated.effective_mode == "scheduled"
    assert updated.effective_at == "2026-08-05 09:00:00"
    assert updated.end_at == "2026-08-20 18:00:00"

    clear_body = AnalyzedPatchIn.model_validate({"end_at": None})
    clear_patch = store.patch_dict_from_api_model(clear_body)
    assert clear_patch == {"end_at": None}
    cleared = store.update_analyzed(an.id, clear_patch, path=msg_db)
    assert cleared is not None
    assert cleared.end_at is None
    assert cleared.effective_at == "2026-08-05 09:00:00"


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


def test_list_analyzed_excludes_expired_unless_include_history(msg_db):
    """默认排除结束时间早于 as_of 的未归档消息；勾选后才纳入（与归档库无关）。"""
    recent = "2026-08-27 10:00:00"
    expired_draft = RawMessageDraft(
        draft_key="hist-old",
        source_id="manual",
        source_label="粘贴",
        content="已过期",
        title="已过期",
        produced_at=recent,
    )
    active_draft = RawMessageDraft(
        draft_key="hist-new",
        source_id="manual",
        source_label="粘贴",
        content="仍有效",
        title="仍有效",
        produced_at=recent,
    )
    raw_old = store.insert_raw_batch([expired_draft], path=msg_db)[0]
    raw_new = store.insert_raw_batch([active_draft], path=msg_db)[0]
    old_msg = store.upsert_analyzed_from_raw(raw_old, path=msg_db)
    new_msg = store.upsert_analyzed_from_raw(raw_new, path=msg_db)
    store.update_analyzed(old_msg.id, {"end_at": "2026-08-27 18:00:00"}, path=msg_db)
    store.update_analyzed(new_msg.id, {"end_at": "2026-08-30 18:00:00"}, path=msg_db)

    as_of = "2026-08-28 12:00:00"
    active_only, active_total = store.list_analyzed(
        store.ListQuery(as_of=as_of, default_end_days=5),
        path=msg_db,
    )
    assert active_total == 1
    assert active_only[0].title == "仍有效"

    with_hist, hist_total = store.list_analyzed(
        store.ListQuery(include_history=True, as_of=as_of, default_end_days=5),
        path=msg_db,
    )
    assert hist_total == 2
    assert {r.title for r in with_hist} == {"已过期", "仍有效"}

    # 无显式 end_at 时，拉长默认有效期会把「按默认天数已过期」的消息重新纳入
    bare = RawMessageDraft(
        draft_key="hist-bare",
        source_id="manual",
        source_label="粘贴",
        content="默认有效期",
        title="默认有效期",
        produced_at="2026-08-01 10:00:00",
    )
    bare_raw = store.insert_raw_batch([bare], path=msg_db)[0]
    bare_msg = store.upsert_analyzed_from_raw(
        bare_raw,
        patch={"effective_mode": "scheduled", "effective_at": "2026-08-27 10:00:00"},
        path=msg_db,
    )
    # scheduled 生效，避免 archive_immediate_expired 清掉
    assert bare_msg.effective_mode == "scheduled"

    short_days, short_total = store.list_analyzed(
        store.ListQuery(as_of=as_of, default_end_days=1, q="默认有效期"),
        path=msg_db,
    )
    assert short_total == 0
    assert short_days == []

    long_days, long_total = store.list_analyzed(
        store.ListQuery(as_of=as_of, default_end_days=5, q="默认有效期"),
        path=msg_db,
    )
    assert long_total == 1
    assert long_days[0].title == "默认有效期"

