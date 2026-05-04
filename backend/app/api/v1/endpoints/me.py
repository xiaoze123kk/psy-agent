from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User, utcnow
from app.db.session import get_db_session
from app.schemas.settings import UserSettingsResponse, UserSettingsUpdateRequest


router = APIRouter(prefix="/me", tags=["user"])


@router.patch("/settings", response_model=UserSettingsResponse)
async def update_settings(
    payload: UserSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> UserSettingsResponse:
    settings = current_user.settings
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User settings are incomplete.",
        )

    if payload.memory_mode is not None:
        settings.memory_mode = payload.memory_mode.value
    if payload.companion_style is not None:
        settings.companion_style = payload.companion_style
    if payload.voice_enabled is not None:
        settings.voice_enabled = payload.voice_enabled
    if payload.save_voice_audio is not None:
        settings.save_voice_audio = payload.save_voice_audio

    settings.updated_at = utcnow()
    db.commit()
    db.refresh(settings)

    return UserSettingsResponse(
        memory_mode=settings.memory_mode,
        companion_style=settings.companion_style,
        voice_enabled=settings.voice_enabled,
        save_voice_audio=settings.save_voice_audio,
    )
