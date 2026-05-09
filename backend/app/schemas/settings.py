from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import MemoryMode
from app.services.companion_style import MAX_COMPANION_STYLE_LENGTH


class UserSettingsUpdateRequest(BaseModel):
    memory_mode: MemoryMode | None = None
    companion_style: str | None = Field(default=None, max_length=MAX_COMPANION_STYLE_LENGTH)
    voice_enabled: bool | None = None
    save_voice_audio: bool | None = None
    save_transcript: bool | None = None


class UserSettingsResponse(BaseModel):
    memory_mode: MemoryMode
    companion_style: str
    voice_enabled: bool
    save_voice_audio: bool
    save_transcript: bool
