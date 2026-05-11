from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import VoiceSession, utcnow


def build_ws_url(voice_session_id: str) -> str:
    return f"/api/v1/voice/sessions/{voice_session_id}/ws"


def create_voice_session(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    mode: str,
    save_transcript: bool,
) -> VoiceSession:
    session = VoiceSession(
        user_id=user_id,
        thread_id=thread_id,
        mode=mode,
        save_transcript=save_transcript,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def end_voice_session(db: Session, *, session_id: str, status: str = "ended") -> None:
    session = db.scalar(select(VoiceSession).where(VoiceSession.id == session_id))
    if session is not None:
        session.status = status
        session.ended_at = utcnow()
        db.commit()


def get_voice_session(db: Session, session_id: str) -> VoiceSession | None:
    return db.scalar(select(VoiceSession).where(VoiceSession.id == session_id))
