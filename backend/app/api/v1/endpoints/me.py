from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User, utcnow
from app.db.session import get_db_session
from app.schemas.companion_styles import CompanionStyleListResponse, CompanionStyleReplaceRequest
from app.schemas.settings import UserSettingsResponse, UserSettingsUpdateRequest
from app.services.companion_style import normalize_custom_companion_style
from app.services.companion_style_library import (
    CompanionStyleLibraryError,
    list_companion_styles,
    replace_companion_styles,
    sync_companion_style_from_definition,
)


router = APIRouter(prefix="/me", tags=["user"])


@router.get("/companion-styles", response_model=CompanionStyleListResponse)
async def get_companion_styles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompanionStyleListResponse:
    return list_companion_styles(db, current_user)


@router.put("/companion-styles", response_model=CompanionStyleListResponse)
async def put_companion_styles(
    payload: CompanionStyleReplaceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompanionStyleListResponse:
    try:
        return replace_companion_styles(db, current_user, payload)
    except CompanionStyleLibraryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        sync_companion_style_from_definition(db, current_user, payload.companion_style, commit=False)

    settings.updated_at = utcnow()
    db.commit()
    db.refresh(settings)

    return UserSettingsResponse(
        memory_mode=settings.memory_mode,
        companion_style=normalize_custom_companion_style(settings.companion_style),
    )
