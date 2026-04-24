from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MemoryItemResponse(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    created_at: datetime
    updated_at: datetime


class ListMemoriesResponse(BaseModel):
    items: list[MemoryItemResponse]


class UpdateMemoryRequest(BaseModel):
    content: str


class MemoryMutationResponse(BaseModel):
    memory_id: str
    content: str | None = None
    status: str


class StatusResponse(BaseModel):
    status: str
