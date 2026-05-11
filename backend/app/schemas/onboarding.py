from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import MemoryMode
from app.services.companion_style import MAX_COMPANION_STYLE_LENGTH


class OnboardingRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=80)
    usage_goals: list[str] = Field(default_factory=list)
    companion_style: str = Field(default="", max_length=MAX_COMPANION_STYLE_LENGTH)
    memory_mode: MemoryMode = MemoryMode.summary_only
    voice_enabled: bool = False
    initial_mood_score: int | None = Field(default=None, ge=1, le=5)
    initial_mood_tags: list[str] = Field(default_factory=list)
    initial_mood_note: str | None = None


class OnboardingResponse(BaseModel):
    ok: bool
    profile_completed: bool
