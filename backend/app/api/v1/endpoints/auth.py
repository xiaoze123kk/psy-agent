from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.models import RefreshToken, User, UserProfile, UserSettings, utcnow
from app.db.session import get_db_session
from app.schemas.auth import (
    CaptchaResponse,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.schemas.common import infer_user_mode
from app.services.captcha_service import captcha_store
from app.services.companion_style import normalize_custom_companion_style
from app.services.login_attempt_service import login_attempt_store


router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _default_nickname(username: str) -> str:
    return username[:20] or "user"


def _dev_email_placeholder(username: str) -> str | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    return f"{username}@local.invalid"


def _verify_captcha(captcha_id: str, captcha_code: str) -> None:
    if not captcha_store.verify(captcha_id, captcha_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图形验证码错误或已过期。",
        )


def _profile_user_mode(user: User) -> str:
    return getattr(user.profile, "user_mode", "adult") if user.profile else "adult"


def _profile_onboarding_completed(user: User) -> bool:
    return bool(getattr(user.profile, "onboarding_completed", False)) if user.profile else False


def _issue_refresh_token(db: Session, user: User) -> str:
    token_id = str(uuid4())
    refresh_token = create_refresh_token(user.id, token_id=token_id)
    db.add(
        RefreshToken(
            id=token_id,
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            status="active",
            expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    return refresh_token


def _issue_token_pair(db: Session, user: User) -> tuple[str, str]:
    return create_access_token(user.id), _issue_refresh_token(db, user)


def _validate_refresh_token(db: Session, refresh_token: str) -> tuple[RefreshToken, User]:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token_id = payload.get("jti")
    if not token_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is missing token id.")

    token_record = db.scalar(select(RefreshToken).where(RefreshToken.id == token_id))
    if token_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found.")

    now = utcnow()
    if token_record.status != "active" or token_record.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is no longer active.")
    if token_record.expires_at <= now:
        token_record.status = "revoked"
        token_record.revoked_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired.")
    if token_record.token_hash != hash_token(refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token mismatch.")

    user = db.scalar(
        select(User).where(
            User.id == payload["sub"],
            User.id == token_record.user_id,
            User.status == "active",
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")
    return token_record, user


def _revoke_refresh_token(token_record: RefreshToken, *, status_value: str) -> None:
    token_record.status = status_value
    token_record.last_used_at = utcnow()
    token_record.revoked_at = utcnow()


def _register_response(user: User, access_token: str, refresh_token: str, user_mode) -> RegisterResponse:
    return RegisterResponse(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_in=settings.access_token_ttl_seconds,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
        user_mode=user_mode,
        onboarding_completed=False,
    )


def _login_response(user: User, access_token: str, refresh_token: str) -> LoginResponse:
    return LoginResponse(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_in=settings.access_token_ttl_seconds,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
        user_mode=_profile_user_mode(user),
        onboarding_completed=_profile_onboarding_completed(user),
    )


@router.get("/captcha", response_model=CaptchaResponse)
async def captcha() -> CaptchaResponse:
    return CaptchaResponse(**captcha_store.create())


@router.post("/register", response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db_session),
) -> RegisterResponse:
    _verify_captcha(payload.captcha_id, payload.captcha_code)
    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    username = _normalize_username(payload.username)
    existing = db.scalar(select(User).where(User.username == username, User.deleted_at.is_(None)))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被使用。",
        )

    user_mode = infer_user_mode(payload.age_range)
    user = User(
        id=str(uuid4()),
        username=username,
        email=_dev_email_placeholder(username),
        password_hash=hash_password(payload.password),
    )
    profile = UserProfile(
        user_id=user.id,
        nickname=_default_nickname(username),
        age_range=payload.age_range.value,
        user_mode=user_mode.value,
        usage_goals=[],
        onboarding_completed=False,
    )
    user_settings = UserSettings(
        user_id=user.id,
        memory_mode="summary_only",
        companion_style="",
        crisis_resource_region="CN",
    )
    db.add_all([user, profile, user_settings])
    access_token, refresh_token = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)

    return _register_response(user, access_token, refresh_token, user_mode)


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> LoginResponse:
    _verify_captcha(payload.captcha_id, payload.captcha_code)
    username = _normalize_username(payload.username)
    client_ip = request.client.host if request.client else "unknown"

    blocked, block_reason = login_attempt_store.is_blocked(client_ip, username)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=block_reason,
        )

    user = db.scalar(select(User).where(User.username == username, User.status == "active"))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_attempt_store.record_failure(client_ip, username, "invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    login_attempt_store.clear(client_ip, username)
    access_token, refresh_token = _issue_token_pair(db, user)
    db.commit()
    db.refresh(user)
    return _login_response(user, access_token, refresh_token)


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db_session),
) -> RefreshTokenResponse:
    token_record, user = _validate_refresh_token(db, payload.refresh_token)
    access_token, next_refresh_token = _issue_token_pair(db, user)
    _revoke_refresh_token(token_record, status_value="rotated")
    db.commit()
    return RefreshTokenResponse(
        user_id=user.id,
        access_token=access_token,
        refresh_token=next_refresh_token,
        access_expires_in=settings.access_token_ttl_seconds,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    db: Session = Depends(get_db_session),
) -> Response:
    token_record, _ = _validate_refresh_token(db, payload.refresh_token)
    _revoke_refresh_token(token_record, status_value="revoked")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        username=current_user.username,
        email=current_user.email,
        nickname=profile.nickname,
        age_range=profile.age_range,
        user_mode=profile.user_mode,
        usage_goals=list(profile.usage_goals or []),
        onboarding_completed=profile.onboarding_completed,
        memory_mode=settings.memory_mode,
        companion_style=normalize_custom_companion_style(settings.companion_style),
    )
