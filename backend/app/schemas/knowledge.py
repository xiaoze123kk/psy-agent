from __future__ import annotations

from datetime import datetime

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


class AskKnowledgeResponse(BaseModel):
    answer: KnowledgeAnswer
    related_articles: list[KnowledgeSearchItemResponse]
    continue_chat_payload: ContinueChatPayload
    risk_level: str = "L0"
