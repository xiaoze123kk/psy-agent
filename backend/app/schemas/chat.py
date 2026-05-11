from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import InputType, RiskLevel, ThreadMode, UserMode
from app.schemas.memory import MemoryReferenceResponse

DeliveryStatus = Literal["generated", "failed_no_reply", "safety_fallback"]
TurnStatus = Literal["accepted", "running", "completed", "failed"]
MemoryJobStatus = Literal["pending", "running", "completed", "failed", "skipped"]


class StartThreadRequest(BaseModel):
    mode: ThreadMode = ThreadMode.companion
    title: str | None = None


class StartThreadResponse(BaseModel):
    thread_id: str
    langgraph_thread_id: str
    mode: str
    title: str
    updated_at: datetime


class ThreadListItem(BaseModel):
    thread_id: str
    title: str
    mode: str
    last_summary: str | None
    last_risk_level: str
    updated_at: datetime


class ThreadListResponse(BaseModel):
    items: list[ThreadListItem]


class SendMessageRequest(BaseModel):
    user_id: str | None = None
    client_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    content: str
    input_type: InputType = InputType.text
    user_mode: UserMode | None = None


class AssistantMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    assistant_text: str
    risk_level: RiskLevel
    intent: str
    suggested_actions: list[str]
    session_summary: str
    should_write_memory: bool
    referenced_memories: list[MemoryReferenceResponse] = Field(default_factory=list)
    referenced_counseling_examples: list[dict] = Field(default_factory=list)
    delivery_status: DeliveryStatus = "generated"
    failure_reason: str | None = None
    retryable: bool = False
    trace_summary: dict[str, object] = Field(default_factory=dict)
    memory_job_id: str | None = None
    memory_job_status: MemoryJobStatus = "skipped"
    created_at: datetime


class SendMessageResponse(BaseModel):
    thread_id: str
    message_id: str
    assistant_message_id: str | None
    client_message_id: str | None = None
    turn_id: str | None = None
    turn_status: TurnStatus = "completed"
    assistant_message: AssistantMessageResponse | None
    delivery_status: DeliveryStatus
    failure_reason: str | None = None
    retryable: bool = False
    trace_summary: dict[str, object] = Field(default_factory=dict)


class MessageItemResponse(BaseModel):
    id: str
    role: str
    content: str
    input_type: str
    risk_level: str | None
    metadata: dict
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageItemResponse]
