from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import MemoryMode, UserMode


PrivacyDataScope = Literal["memories", "chat", "moods", "feedback", "all_non_account"]


class PrivacySettingsSnapshot(BaseModel):
    memory_mode: MemoryMode


class PrivacyDataCounts(BaseModel):
    memories: int
    chat_threads: int
    chat_messages: int
    mood_logs: int
    test_history: int
    feedback: int
    risk_events: int


class PrivacySummaryResponse(BaseModel):
    user_id: str
    user_mode: UserMode
    settings: PrivacySettingsSnapshot
    data_counts: PrivacyDataCounts
    latest_activity_at: datetime | None = None


class DataDeleteRequest(BaseModel):
    scope: PrivacyDataScope


class AccountDeleteRequest(BaseModel):
    confirmation: Literal["DELETE"]


class PrivacyMutationResponse(BaseModel):
    status: str
    scope: str
    affected_counts: dict[str, int]
