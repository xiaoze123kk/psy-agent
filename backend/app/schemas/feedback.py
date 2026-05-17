from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


LegacyFeedbackTarget = Literal["assistant_message", "knowledge_answer", "test_result"]
ConversationQualityFeedback = Literal[
    "missed",
    "too_analytic",
    "too_generic",
    "too_many_questions",
    "good",
]


class FeedbackCreateRequest(BaseModel):
    target_type: LegacyFeedbackTarget | None = None
    target_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    feedback: ConversationQualityFeedback | None = None
    optional_note: str | None = None

    @model_validator(mode="after")
    def validate_supported_payload(self) -> "FeedbackCreateRequest":
        is_light_feedback = self.thread_id is not None or self.turn_id is not None or self.feedback is not None
        if is_light_feedback:
            if not self.thread_id or not self.turn_id or self.feedback is None:
                raise ValueError("thread_id, turn_id and feedback are required for conversation quality feedback.")
            return self

        if self.target_type is None or not self.target_id or self.rating is None:
            raise ValueError("target_type, target_id and rating are required for feedback.")
        return self


class FeedbackResponse(BaseModel):
    feedback_id: str
    status: str = "recorded"
