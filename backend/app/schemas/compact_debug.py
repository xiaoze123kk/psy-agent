from __future__ import annotations

from pydantic import BaseModel, Field


class CompactDebugResponse(BaseModel):
    has_compact: bool
    latest_event: dict[str, object] = Field(default_factory=dict)
    state: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    prompt_view: str


class CompactPreviewRequest(BaseModel):
    focus: list[str] = Field(default_factory=list, max_length=8)
    max_recent_messages: int = Field(default=10, ge=1, le=30)


class CompactPreviewResponse(BaseModel):
    persisted: bool
    pack: dict[str, object] = Field(default_factory=dict)
    prompt_diff: dict[str, str] = Field(default_factory=dict)
