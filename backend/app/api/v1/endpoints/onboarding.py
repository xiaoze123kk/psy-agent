from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import MoodLog, User, utcnow
from app.db.session import get_db_session
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.services.companion_style_library import sync_companion_style_from_definition


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("", response_model=OnboardingResponse)
async def save_onboarding(
    payload: OnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> OnboardingResponse:
    current_user.profile.nickname = payload.nickname
    current_user.profile.usage_goals = list(payload.usage_goals)
    current_user.profile.onboarding_completed = True
    current_user.profile.updated_at = utcnow()

    sync_companion_style_from_definition(db, current_user, payload.companion_style, commit=False)
    current_user.settings.memory_mode = payload.memory_mode.value
    current_user.settings.updated_at = utcnow()

    if payload.initial_mood_score is not None:
        mood_log = MoodLog(
            user_id=current_user.id,
            mood_score=payload.initial_mood_score,
            mood_tags=list(payload.initial_mood_tags),
            note=payload.initial_mood_note,
            source="onboarding",
        )
        db.add(mood_log)

    db.commit()
    return OnboardingResponse(ok=True, profile_completed=True)
