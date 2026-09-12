"""消息 AI 分析测试。"""

from __future__ import annotations

import json

import pytest

from vr.message import analyze as analyze_mod, store
from vr.message.schemas import RawMessageDraft


@pytest.fixture
def msg_db(tmp_path):
    path = str(tmp_path / "messages.db")
    store.init_db(path)
    return path


def test_synthesize_ai_impact_level_basic():
    level = analyze_mod.synthesize_ai_impact_level(
        {
            "scope": "market",
            "magnitude": 5,
            "actionability": 5,
            "credibility": 5,
            "time_sensitivity": 5,
            "is_rumor": False,
        }
    )
    assert level == "critical"


def test_synthesize_rumor_demote_and_duplicate_cap():
    demoted = analyze_mod.synthesize_ai_impact_level(
        {
            "scope": "sector",
            "magnitude": 4,
            "actionability": 4,
            "credibility": 4,
            "time_sensitivity": 4,
            "is_rumor": True,
        },
        freshness="new",
    )
    assert demoted == "medium"

    capped = analyze_mod.synthesize_ai_impact_level(
        {
            "scope": "market",
            "magnitude": 5,
            "actionability": 5,
            "credibility": 5,
            "time_sensitivity": 5,
            "is_rumor": False,
        },
        freshness="duplicate",
    )
    assert capped == "medium"


def test_parse_llm_patch(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d1",
            source_id="manual",
            source_label="粘贴",
            content="低空经济政策再出利好，多家公司受益",
            title="低空经济",
            keywords=["9"],
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)
    obj = {
        "title": "低空经济政策",
        "summary": "低空经济再出政策利好",
        "detail": "AI 不应改写 detail",
        "keywords": ["低空经济", "政策"],
        "marks": ["highlight"],
        "effective_mode": "scheduled",
        "effective_at": "2026-12-31 00:00:00",
        "targets": [{"kind": "theme", "name": "低空经济", "code": None}],
        "scope": "theme",
        "magnitude": 4,
        "actionability": 4,
        "credibility": 4,
        "time_sensitivity": 3,
        "is_rumor": False,
        "rationale": "板块政策力度较高",
        "freshness": "new",
        "effect_status": "not_erupted",
    }
    patch = analyze_mod._parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    assert patch["ai_impact_level"] in analyze_mod._IMPACT
    assert patch["impact_level"] == patch["ai_impact_level"] or patch["impact_level"] in analyze_mod._IMPACT
    assert patch["impact_factors"]["magnitude"] == 4
    assert patch["impact_rationale"] == "板块政策力度较高"
    assert patch["freshness"] == "new"
    assert patch["keywords"] == ["9", "低空经济", "政策"]
    assert "detail" not in patch
    assert "marks" not in patch
    assert "effective_mode" not in patch
    assert "effective_at" not in patch


def test_parse_llm_patch_preserves_edited_detail(msg_db):
    """人工改过的详情是分析输入，AI 不得写回覆盖。"""
    drafts = [
        RawMessageDraft(
            draft_key="d1-detail",
            source_id="manual",
            source_label="粘贴",
            content="原始入库正文",
            title="原标题",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)
    edited = store.update_analyzed(
        analyzed.id,
        {"detail": "人工改过的详情正文", "analyzed_by": "human"},
        path=msg_db,
    )
    assert edited is not None
    patch = analyze_mod._parse_llm_patch(
        {
            "title": "AI 标题",
            "summary": "AI 摘要",
            "detail": "模型若输出 detail 也应被忽略",
            "keywords": ["新增"],
            "freshness": "new",
            "effect_status": "not_erupted",
            "scope": "other",
            "magnitude": 3,
            "actionability": 3,
            "credibility": 3,
            "time_sensitivity": 3,
            "is_rumor": False,
            "rationale": "常规",
        },
        raw=raw,
        analyzed=edited,
    )
    assert "detail" not in patch
    prompt = analyze_mod.build_user_prompt(raw, edited)
    assert "人工改过的详情正文" in prompt
    assert "原始入库正文" not in prompt.split("【正文】")[-1]


def test_parse_llm_patch_legacy_impact_level(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d1-legacy",
            source_id="manual",
            source_label="粘贴",
            content="低空经济政策再出利好，多家公司受益",
            title="低空经济",
            keywords=["9"],
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)
    obj = {
        "title": "低空经济政策",
        "summary": "低空经济再出政策利好",
        "targets": [{"kind": "theme", "name": "低空经济", "code": None}],
        "impact_level": "high",
        "freshness": "new",
        "effect_status": "not_erupted",
    }
    patch = analyze_mod._parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    assert patch["ai_impact_level"] == "high"
    assert patch["impact_factors"] is None
    assert patch["keywords"] == ["9"]


def test_parse_llm_patch_preserves_targets(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d1b",
            source_id="manual",
            source_label="粘贴",
            content="测试",
            title="测试",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(
        raw,
        patch={"targets": [{"kind": "stock", "code": "600000", "name": "浦发银行"}]},
        path=msg_db,
    )
    obj = {
        "summary": "摘要",
        "targets": [{"kind": "theme", "name": "低空经济", "code": None}],
        "impact_level": "medium",
        "freshness": "new",
        "effect_status": "not_erupted",
    }
    patch = analyze_mod._parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    assert len(patch["targets"]) == 2
    assert patch["targets"][0]["code"] == "600000"


def test_extract_url_from_content(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d1c",
            source_id="manual",
            source_label="粘贴",
            content="详见 https://example.com/news/1 报道",
            title="链接测试",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)
    patch = analyze_mod._parse_llm_patch({"summary": "摘要"}, raw=raw, analyzed=analyzed)
    assert patch["url"] == "https://example.com/news/1"


def test_analyze_one_mock(msg_db, monkeypatch):
    drafts = [
        RawMessageDraft(
            draft_key="d2",
            source_id="manual",
            source_label="粘贴",
            content="测试消息内容",
            title="测试",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)

    fake_json = json.dumps(
        {
            "title": "测试",
            "summary": "测试摘要",
            "keywords": ["测试"],
            "targets": [],
            "scope": "other",
            "magnitude": 3,
            "actionability": 3,
            "credibility": 3,
            "time_sensitivity": 3,
            "is_rumor": False,
            "rationale": "常规测试消息",
            "freshness": "new",
            "effect_status": "not_erupted",
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(analyze_mod, "_llm_complete", lambda cfg, user, retry_hint="", system=None, skeleton=None: fake_json)
    monkeypatch.setattr(store, "DB_PATH", msg_db)
    monkeypatch.setattr(store, "_INITED", False)

    result = analyze_mod.analyze_one(
        {"provider": "openai", "baseURL": "http://127.0.0.1:9999", "apiKey": "x", "model": "m"},
        analyzed_id=analyzed.id,
    )
    assert result.summary == "测试摘要"
    assert result.detail == raw.content
    assert result.analyzed_by == "ai"
    assert result.status == "draft"
    assert result.ai_impact_level is not None
    assert result.ai_impact_level in analyze_mod._IMPACT
    assert result.impact_rationale == "常规测试消息"
    assert result.impact_factors is not None


def test_analyze_one_preserves_edited_detail(msg_db, monkeypatch):
    drafts = [
        RawMessageDraft(
            draft_key="d2-edit-detail",
            source_id="manual",
            source_label="粘贴",
            content="原始正文",
            title="原标题",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(raw, path=msg_db)
    store.update_analyzed(
        analyzed.id,
        {"detail": "已人工修订的详情", "analyzed_by": "human"},
        path=msg_db,
    )

    fake_json = json.dumps(
        {
            "title": "AI 标题",
            "summary": "AI 摘要",
            "detail": "不应落盘的模型详情",
            "keywords": [],
            "targets": [],
            "scope": "other",
            "magnitude": 3,
            "actionability": 3,
            "credibility": 3,
            "time_sensitivity": 3,
            "is_rumor": False,
            "rationale": "常规",
            "freshness": "new",
            "effect_status": "not_erupted",
        },
        ensure_ascii=False,
    )
    seen_prompt: list[str] = []

    def _fake_llm(cfg, user, retry_hint="", system=None, skeleton=None):
        seen_prompt.append(user)
        return fake_json

    monkeypatch.setattr(analyze_mod, "_llm_complete", _fake_llm)
    monkeypatch.setattr(store, "DB_PATH", msg_db)
    monkeypatch.setattr(store, "_INITED", False)

    result = analyze_mod.analyze_one(
        {"provider": "openai", "baseURL": "http://127.0.0.1:9999", "apiKey": "x", "model": "m"},
        analyzed_id=analyzed.id,
    )
    assert result.detail == "已人工修订的详情"
    assert result.summary == "AI 摘要"
    assert seen_prompt and "已人工修订的详情" in seen_prompt[0]
    assert "原始正文" not in seen_prompt[0].split("【正文】")[-1]


def test_analyze_one_keeps_manual_working_updates_ai(msg_db, monkeypatch):
    drafts = [
        RawMessageDraft(
            draft_key="d2-manual",
            source_id="manual",
            source_label="粘贴",
            content="测试消息内容",
            title="测试",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(
        raw, patch={"impact_level": "low"}, path=msg_db
    )
    store.update_analyzed(analyzed.id, {"impact_level": "noise"}, path=msg_db)

    fake_json = json.dumps(
        {
            "title": "测试",
            "summary": "测试摘要",
            "keywords": [],
            "targets": [],
            "scope": "market",
            "magnitude": 5,
            "actionability": 5,
            "credibility": 5,
            "time_sensitivity": 5,
            "is_rumor": False,
            "rationale": "重大",
            "freshness": "new",
            "effect_status": "not_erupted",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(analyze_mod, "_llm_complete", lambda cfg, user, retry_hint="", system=None, skeleton=None: fake_json)
    monkeypatch.setattr(store, "DB_PATH", msg_db)
    monkeypatch.setattr(store, "_INITED", False)

    result = analyze_mod.analyze_one(
        {"provider": "openai", "baseURL": "http://127.0.0.1:9999", "apiKey": "x", "model": "m"},
        analyzed_id=analyzed.id,
    )
    assert result.impact_manual is True
    assert result.impact_level == "noise"
    assert result.ai_impact_level == "critical"


def test_analyze_impact_only_mock(msg_db, monkeypatch):
    drafts = [
        RawMessageDraft(
            draft_key="d-impact",
            source_id="manual",
            source_label="粘贴",
            content="原正文不应被影响模式改写",
            title="原标题",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(
        raw,
        patch={"summary": "原摘要", "impact_level": "low"},
        path=msg_db,
    )

    fake_json = json.dumps(
        {
            "scope": "market",
            "magnitude": 5,
            "actionability": 5,
            "credibility": 5,
            "time_sensitivity": 5,
            "is_rumor": False,
            "rationale": "仅重算影响档",
            "title": "不应写入",
            "summary": "不应写入摘要",
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(
        analyze_mod,
        "_llm_complete",
        lambda cfg, user, retry_hint="", system=None, skeleton=None: fake_json,
    )
    monkeypatch.setattr(store, "DB_PATH", msg_db)
    monkeypatch.setattr(store, "_INITED", False)

    result = analyze_mod.analyze_one(
        {"provider": "openai", "baseURL": "http://127.0.0.1:9999", "apiKey": "x", "model": "m"},
        analyzed_id=analyzed.id,
        mode="impact",
    )
    assert result.title == "原标题"
    assert result.summary == "原摘要"
    assert result.detail == raw.content
    assert result.ai_impact_level == "critical"
    assert result.impact_rationale == "仅重算影响档"
    assert result.impact_level == "critical"
    assert result.analyzed_by == "ai"


def test_parse_impact_only_patch(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d-impact-parse",
            source_id="manual",
            source_label="粘贴",
            content="正文",
            title="标题",
        )
    ]
    raw = store.insert_raw_batch(drafts, path=msg_db)[0]
    analyzed = store.upsert_analyzed_from_raw(
        raw, patch={"summary": "摘要", "impact_level": "low"}, path=msg_db
    )
    patch = analyze_mod._parse_impact_only_patch(
        {
            "scope": "stock",
            "magnitude": 2,
            "actionability": 2,
            "credibility": 3,
            "time_sensitivity": 2,
            "is_rumor": False,
            "rationale": "个股弱消息",
        },
        raw=raw,
        analyzed=analyzed,
    )
    assert set(patch.keys()) == {
        "ai_impact_level",
        "impact_level",
        "impact_factors",
        "impact_rationale",
        "analyzed_by",
    }
    assert patch["impact_rationale"] == "个股弱消息"
    assert "title" not in patch
    assert "summary" not in patch
