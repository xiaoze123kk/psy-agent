from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryItemResponse(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int | None = None
    confidence: float | None = None
    review_state: str | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0


class MemoryReferenceResponse(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    title: str | None = None
    score: float | None = None
    why_selected: str | None = None
    freshness_warning: str | None = None


class ListMemoriesResponse(BaseModel):
    items: list[MemoryItemResponse]
    total: int = 0
    limit: int = 50
    offset: int = 0


class UpdateMemoryRequest(BaseModel):
    content: str
    title: str | None = None
    tags: list[str] | None = None


class MemoryMutationResponse(BaseModel):
    memory_id: str
    content: str | None = None
    status: str


class StatusResponse(BaseModel):
    status: str


class SearchMemoriesRequest(BaseModel):
    query: str
    risk_level: str = "L0"
    control_category: str | None = None
    limit: int = Field(default=5, ge=1, le=200)


class SearchMemoryItem(BaseModel):
    memory_id: str
    memory_type: str
    title: str
    summary: str
    content: str
    tags: list[str] = Field(default_factory=list)
    visibility: str
    updated_at: datetime | str
    score: float
    why_selected: str
    freshness_warning: str = ""
    source: str


class SearchMemoriesResponse(BaseModel):
    items: list[SearchMemoryItem]


class MemoryFeedbackRequest(BaseModel):
    feedback: str
    note: str | None = None


class MemoryAuditItem(BaseModel):
    operation_id: str
    memory_id: str | None
    action: str
    reason: str | None = None
    actor: str
    before_value: dict | None = None
    after_value: dict | None = None
    created_at: datetime


class MemoryAuditResponse(BaseModel):
    items: list[MemoryAuditItem]
    total: int = 0
    limit: int = 50
    offset: int = 0


class MemoryConsolidationResponse(BaseModel):
    run_id: str
    status: str
    sessions_reviewed: int = 0
    memories_touched: int = 0
    error_message: str | None = None
