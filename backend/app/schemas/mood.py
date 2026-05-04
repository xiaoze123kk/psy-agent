from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MoodLogRequest(BaseModel):
    mood_score: int = Field(ge=1, le=5)
    anxiety_score: int | None = Field(default=None, ge=1, le=5)
    energy_score: int | None = Field(default=None, ge=1, le=5)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    mood_tags: list[str] = Field(default_factory=list)
    note: str | None = None


class MoodLogResponse(BaseModel):
    log_id: str
    created_at: datetime
    mood_score: int


class DailyMoodPoint(BaseModel):
    date: str
    mood_score: float
    tags: list[str]


class MoodTrendResponse(BaseModel):
    range: str
    avg_mood_score: float
    top_tags: list[str]
    daily: list[DailyMoodPoint]
    summary: str


class WeeklySummaryResponse(BaseModel):
    range: str = "7d"
    summary: str
    top_tags: list[str]
    suggested_actions: list[str]
    generated_by: str = "fallback"  # "llm" | "fallback"
