from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.companion_style import (
    MAX_COMPANION_STYLE_LENGTH,
    MAX_COMPANION_STYLE_TITLE_LENGTH,
)


class CompanionStyleItem(BaseModel):
    style_id: str
    title: str
    definition: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class CompanionStyleUpsertItem(BaseModel):
    style_id: str | None = Field(default=None, max_length=80)
    client_id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=MAX_COMPANION_STYLE_TITLE_LENGTH)
    definition: str = Field(min_length=1, max_length=MAX_COMPANION_STYLE_LENGTH)


class CompanionStyleReplaceRequest(BaseModel):
    items: list[CompanionStyleUpsertItem] = Field(default_factory=list)
    selected_style_id: str | None = Field(default="default", max_length=128)


class CompanionStyleListResponse(BaseModel):
    items: list[CompanionStyleItem]
    selected_style_id: str
    companion_style: str
