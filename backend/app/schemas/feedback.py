from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreateRequest(BaseModel):
    target_type: Literal["assistant_message", "knowledge_answer", "test_result"]
    target_id: str
    rating: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    note: str | None = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    status: str = "recorded"
