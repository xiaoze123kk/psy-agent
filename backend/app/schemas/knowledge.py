from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeSearchItemResponse(BaseModel):
    article_id: str
    slug: str
    title: str
    category: str
    audience: str
    summary_30s: str
    tags: list[str]


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeSearchItemResponse]


class KnowledgeArticleResponse(BaseModel):
    article_id: str
    slug: str
    title: str
    category: str
    audience: str
    summary_30s: str
    explanation_3min: str
    advanced_text: str | None
    common_misunderstandings: list[str]
    actions: list[str]
    seek_help_when: list[str]
    source_refs: list[dict]
    tags: list[str]
    updated_at: datetime


class AskKnowledgeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    use_my_context: bool = True
    thread_id: str | None = None


class KnowledgeAnswer(BaseModel):
    summary_30s: str
    explanation_3min: str
    actions: list[str]
    seek_help_when: list[str]


class ContinueChatPayload(BaseModel):
    mode: str
    context_type: str
    article_id: str | None = None
    thread_id: str | None = None


class KnowledgeSourceRefResponse(BaseModel):
    source_name: str
    source_url: str | None = None
    license: str | None = None
    article_id: str
    article_title: str
    chunk_id: str | None = None
    chunk_index: int | None = None
    score: int | None = None


class AskKnowledgeResponse(BaseModel):
    answer: KnowledgeAnswer
    related_articles: list[KnowledgeSearchItemResponse]
    coverage_status: Literal["sufficient", "partial", "insufficient", "not_applicable"] = "sufficient"
    scope_status: Literal["in_scope", "out_of_scope"] = "in_scope"
    confidence: Literal["high", "medium", "low"] = "high"
    source_refs: list[KnowledgeSourceRefResponse] = Field(default_factory=list)
    gap_id: str | None = None
    continue_chat_payload: ContinueChatPayload
    risk_level: str = "L0"


class KnowledgeGapItemResponse(BaseModel):
    gap_id: str
    question: str
    category: str | None
    audience: str | None
    coverage_status: str
    confidence: str
    top_score: int
    status: str
    hit_count: int
    source_refs: list[dict]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class KnowledgeGapListResponse(BaseModel):
    items: list[KnowledgeGapItemResponse]


class ResolveKnowledgeGapRequest(BaseModel):
    article_id: str | None = None
    reviewer_note: str | None = None


class KnowledgeGapMutationResponse(BaseModel):
    gap_id: str
    status: str
