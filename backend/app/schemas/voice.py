from __future__ import annotations

from pydantic import BaseModel


class VoiceSessionCreateRequest(BaseModel):
    thread_id: str | None = None
    mode: str = "companion"
    save_transcript: bool = True


class VoiceSessionResponse(BaseModel):
    voice_session_id: str
    thread_id: str
    ws_url: str
    protocol: str = "text-simulated-voice-v1"
