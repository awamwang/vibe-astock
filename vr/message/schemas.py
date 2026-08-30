"""消息分析 — Pydantic 模型与枚举。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ImpactLevel = Literal["critical", "high", "medium", "low", "noise"]
Freshness = Literal["new", "follow_up", "duplicate", "rumor"]
EffectStatus = Literal[
    "not_erupted",
    "pending_verify",
    "ongoing_hype",
    "already_hyped",
    "invalid",
]
TargetKind = Literal["market", "sector", "theme", "stock", "other"]
EffectiveMode = Literal["immediate", "scheduled"]
AnalyzedStatus = Literal["draft", "confirmed", "archived"]
AnalyzedBy = Literal["ai", "human", "rule"]
IngestFormat = Literal["plain", "structured", "calendar", "article"]
SourceAdapterType = Literal["manual", "poll", "plugin"]


class ImpactTarget(BaseModel):
    kind: TargetKind
    code: str | None = None
    name: str


class RawMessage(BaseModel):
    id: str
    source_id: str
    source_label: str = ""
    content: str
    title: str = ""
    keywords: list[str] = Field(default_factory=list)
    url: str = ""
    marks: list[str] = Field(default_factory=list)
    content_hash: str = ""
    batch_id: str | None = None
    external_ref: str | None = None
    produced_at: str
    ingested_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class AnalyzedMessage(BaseModel):
    id: str
    raw_ids: list[str] = Field(default_factory=list)
    source_id: str
    source_label: str = ""
    title: str = ""
    keywords: list[str] = Field(default_factory=list)
    url: str = ""
    marks: list[str] = Field(default_factory=list)
    summary: str = ""
    detail: str = ""
    effective_mode: EffectiveMode = "immediate"
    effective_at: str | None = None
    end_at: str | None = None
    produced_at: str
    targets: list[ImpactTarget] = Field(default_factory=list)
    impact_level: ImpactLevel = "medium"
    # 进入消息系统时的初始优先级；不受 AI / 关注词影响，仅手动改档时与 impact_level 同步
    initial_impact_level: ImpactLevel = "medium"
    # 优先级是否被人工指定过
    impact_manual: bool = False
    freshness: Freshness = "new"
    effect_status: EffectStatus = "not_erupted"
    analyzed_at: str | None = None
    analyzed_by: AnalyzedBy | None = None
    version: int = 1
    status: AnalyzedStatus = "draft"
    favorited: bool = False
    followed: bool = False
    matched_follow_keywords: list[str] = Field(default_factory=list)
    matched_follow_blocks: list[str] = Field(default_factory=list)
    matched_current_stock_blocks: list[str] = Field(default_factory=list)


class RawMessageDraft(BaseModel):
    """解析预览草稿，尚未入库。"""
    draft_key: str
    source_id: str
    source_label: str = ""
    content: str
    title: str = ""
    keywords: list[str] = Field(default_factory=list)
    url: str = ""
    marks: list[str] = Field(default_factory=list)
    external_ref: str | None = None
    produced_at: str | None = None
    effective_mode: EffectiveMode = "immediate"
    effective_at: str | None = None
    targets: list[ImpactTarget] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class IngestPayload(BaseModel):
    format: IngestFormat = "plain"
    source_id: str = "manual"
    text: str | None = None
    items: list[dict[str, Any]] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class IngestAdjustPayload(BaseModel):
    """合并或再拆分后的草稿提交。"""
    drafts: list[RawMessageDraft]


class MessageSourceInfo(BaseModel):
    id: str
    label: str
    adapter_type: SourceAdapterType
    enabled: bool = True
    poll_interval_s: int | None = None
    last_poll_at: str | None = None
    last_error: str | None = None


class AnalyzeRequest(BaseModel):
    raw_ids: list[str] = Field(default_factory=list)
    analyzed_ids: list[str] = Field(default_factory=list)


class ListQuery(BaseModel):
    source: str | None = None
    q: str | None = None
    from_dt: str | None = None
    to_dt: str | None = None
    impact_level: str | None = None
    effect_status: str | None = None
    status: str | None = None
    favorited: str | None = None
    followed: str | None = None
    match_current_stock: str | None = None
    stock_code: str | None = None
    # 勾选后才包含结束时间早于 as_of 的未归档消息；已归档消息不在主库，永远搜不到
    include_history: bool = False
    # 未设 end_at 时按生效时间 + N 天计算结束时间（与前端默认有效期一致）
    default_end_days: int = 5
    # 筛选「是否已结束」的参照时间（搜索时间）；空则用查询时的当前时间
    as_of: str | None = None
    sort: Literal[
        "produced_at", "ingested_at", "impact_level", "effect_status", "freshness", "status", "title"
    ] = "produced_at"
    order: Literal["asc", "desc"] = "desc"
    limit: int = 50
    offset: int = 0
