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


def test_parse_llm_patch(msg_db):
    drafts = [
        RawMessageDraft(
            draft_key="d1",
            source_id="paste",
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
        "detail": "正文展开…",
        "keywords": ["低空经济", "政策"],
        "marks": [],
        "effective_mode": "immediate",
        "effective_at": None,
        "targets": [{"kind": "theme", "name": "低空经济", "code": None}],
        "impact_level": "high",
        "freshness": "new",
        "effect_status": "not_erupted",
    }
    patch = analyze_mod._parse_llm_patch(obj, raw=raw, analyzed=analyzed)
    assert patch["impact_level"] == "high"
    assert patch["freshness"] == "new"
    assert patch["keywords"] == ["低空经济", "政策"]


def test_analyze_one_mock(msg_db, monkeypatch):
    drafts = [
        RawMessageDraft(
            draft_key="d2",
            source_id="paste",
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
            "detail": "测试详情",
            "keywords": ["测试"],
            "marks": [],
            "effective_mode": "immediate",
            "effective_at": None,
            "targets": [],
            "impact_level": "medium",
            "freshness": "new",
            "effect_status": "not_erupted",
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(analyze_mod, "_llm_complete", lambda cfg, user, retry_hint="": fake_json)
    monkeypatch.setattr(store, "DB_PATH", msg_db)
    monkeypatch.setattr(store, "_INITED", False)

    result = analyze_mod.analyze_one(
        {"provider": "openai", "baseURL": "http://127.0.0.1:9999", "apiKey": "x", "model": "m"},
        analyzed_id=analyzed.id,
    )
    assert result.summary == "测试摘要"
    assert result.analyzed_by == "ai"
    assert result.status == "draft"


def test_extract_first_json_with_fence():
    text = '说明文字\n```json\n{"summary": "ok", "freshness": "new"}\n```\n'
    obj = analyze_mod.extract_first_json(text)
    assert obj and obj.get("summary") == "ok"
