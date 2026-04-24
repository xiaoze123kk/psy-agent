from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import RiskLevel, SafetyAudience


class SafetyResourceItem(BaseModel):
    resource_type: str
    title: str
    description: str


class SafetyResourcesResponse(BaseModel):
    region: str
    audience: SafetyAudience
    items: list[SafetyResourceItem]


class CrisisEventRequest(BaseModel):
    thread_id: str
    message_id: str | None = None
    risk_level: RiskLevel
    detected_signals: list[str] = Field(default_factory=list)
    action_taken: list[str] = Field(default_factory=list)


class CrisisEventResponse(BaseModel):
    event_id: str
    thread_id: str
    status: str
