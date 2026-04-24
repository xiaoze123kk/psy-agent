from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.models import User, UserProfile, UserSettings
from app.db.session import get_db_session
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.schemas.common import infer_user_mode


router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _default_nickname(email: str) -> str:
    local_part = email.split("@", 1)[0].strip()
    return (local_part or "user")[:20]


@router.post("/register", response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db_session),
) -> RegisterResponse:
    email = _normalize_email(payload.email)
    existing = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user_mode = infer_user_mode(payload.age_range)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    profile = UserProfile(
        user_id=user.id,
        nickname=_default_nickname(email),
        age_range=payload.age_range.value,
        user_mode=user_mode.value,
        usage_goals=[],
        onboarding_completed=False,
    )
    settings = UserSettings(
        user_id=user.id,
        memory_mode="summary_only",
        companion_style="gentle",
        voice_enabled=False,
        save_voice_audio=False,
        save_transcript=True,
        crisis_resource_region="CN",
    )
    db.add_all([profile, settings])
    db.commit()
    db.refresh(user)

    return RegisterResponse(
        user_id=user.id,
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user_mode=user_mode,
        onboarding_completed=False,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db_session),
) -> LoginResponse:
    email = _normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email, User.status == "active"))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    return LoginResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    profile = current_user.profile
    settings = current_user.settings
    if profile is None or settings is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User profile is incomplete.",
        )

    return CurrentUserResponse(
        user_id=current_user.id,
        email=current_user.email,
        nickname=profile.nickname,
        age_range=profile.age_range,
        user_mode=profile.user_mode,
        usage_goals=list(profile.usage_goals or []),
        onboarding_completed=profile.onboarding_completed,
        memory_mode=settings.memory_mode,
        companion_style=settings.companion_style,
        voice_enabled=settings.voice_enabled,
    )
