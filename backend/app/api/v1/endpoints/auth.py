from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    hash_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.models import PasswordResetToken, RefreshToken, User, UserProfile, UserSettings, utcnow
from app.db.session import get_db_session
from app.schemas.auth import (
    CaptchaResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    PasswordResetQuestionRequest,
    PasswordResetQuestionResponse,
    PasswordResetRequest,
    PasswordResetVerifyRequest,
    PasswordResetVerifyResponse,
    RefreshTokenResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.schemas.auth import USERNAME_PATTERN
from app.schemas.common import infer_user_mode
from app.services.captcha_service import captcha_store
from app.services.companion_style import normalize_custom_companion_style
from app.services.login_attempt_service import login_attempt_store


router = APIRouter(prefix="/auth", tags=["auth"])
DEV_SESSION_USERNAME = "local_debug_user"
DEV_SESSION_PASSWORD_MARKER = "dev-session-only"
DEV_SESSION_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

REFRESH_COOKIE_KEY = "rt"
RESET_TOKEN_TTL_SECONDS = 300
AUTO_LOGIN_TTL_SECONDS = 604800
SESSION_TTL_SECONDS = 3600
MAX_ACTIVE_SESSIONS = 5


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _default_nickname(username: str) -> str:
    return username[:20] or "user"


def _dev_email_placeholder(username: str) -> str | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    return f"{username}@local.invalid"


def _is_dev_session_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return settings.secret_key == "dev-only-change-me" and host in DEV_SESSION_ALLOWED_HOSTS


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


def _ensure_dev_session_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == DEV_SESSION_USERNAME, User.deleted_at.is_(None)))
    if user is None:
        user = User(
            username=DEV_SESSION_USERNAME,
            email=_dev_email_placeholder(DEV_SESSION_USERNAME),
            password_hash=hash_password(DEV_SESSION_PASSWORD_MARKER),
        )
        db.add(user)
        db.flush()

    if user.profile is None:
        db.add(
            UserProfile(
                user_id=user.id,
                nickname="本地调试用户",
                age_range="18_plus",
                user_mode="adult",
                usage_goals=[],
                onboarding_completed=True,
            )
        )
    else:
        user.profile.nickname = user.profile.nickname or "本地调试用户"
        user.profile.age_range = user.profile.age_range or "18_plus"
        user.profile.user_mode = user.profile.user_mode or "adult"
        user.profile.onboarding_completed = True

    if user.settings is None:
        db.add(
            UserSettings(
                user_id=user.id,
                memory_mode="summary_only",
                companion_style="",
                crisis_resource_region="CN",
            )
        )

    return user


def _set_refresh_cookie(response: Response, refresh_token: str, auto_login: bool) -> None:
    max_age = AUTO_LOGIN_TTL_SECONDS if auto_login else SESSION_TTL_SECONDS
    cookie_kwargs = {
        "key": REFRESH_COOKIE_KEY,
        "value": refresh_token,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/api/v1/auth",
        "max_age": max_age,
    }
    response.set_cookie(**cookie_kwargs)


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_KEY,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/v1/auth",
    )


def _issue_refresh_token(db: Session, user: User, ttl_seconds: int, auto_login: bool) -> str:
    active_count = db.scalar(
        select(func.count(RefreshToken.id)).where(
            RefreshToken.user_id == user.id,
            RefreshToken.status == "active",
        )
    )
    if active_count and active_count >= MAX_ACTIVE_SESSIONS:
        oldest = db.scalars(
            select(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.status == "active")
            .order_by(RefreshToken.created_at.asc())
            .limit(1)
        ).first()
        if oldest:
            _revoke_refresh_token(oldest, status_value="revoked")
    token_id = str(uuid4())
    refresh_token = create_refresh_token(user.id, token_id=token_id, ttl_seconds=ttl_seconds, token_version=user.token_version)
    db.add(
        RefreshToken(
            id=token_id,
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            auto_login=auto_login,
            status="active",
            expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        )
    )
    _sweep_expired_tokens(db, user.id)
    return refresh_token


def _issue_token_pair(db: Session, user: User, auto_login: bool) -> tuple[str, str]:
    ttl = AUTO_LOGIN_TTL_SECONDS if auto_login else SESSION_TTL_SECONDS
    return create_access_token(user.id, token_version=user.token_version), _issue_refresh_token(db, user, ttl, auto_login=auto_login)


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

    now = _as_utc_aware(utcnow())
    if token_record.status != "active" or token_record.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is no longer active.")
    if _is_expired(token_record.expires_at, now):
        token_record.status = "revoked"
        token_record.revoked_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired.")
    if token_record.token_hash != hash_token(refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token mismatch.")

    user = db.scalar(
        select(User).options(selectinload(User.profile), selectinload(User.settings)).where(
            User.id == payload["sub"],
            User.id == token_record.user_id,
            User.status == "active",
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")
    if payload.get("ver") != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    return token_record, user


def _revoke_refresh_token(token_record: RefreshToken, *, status_value: str) -> None:
    token_record.status = status_value
    token_record.last_used_at = utcnow()
    token_record.revoked_at = utcnow()


def _revoke_all_user_tokens(db: Session, user: User) -> None:
    active_tokens = db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.status == "active")
    ).all()
    for rt in active_tokens:
        _revoke_refresh_token(rt, status_value="revoked")


def _rotate_password(db: Session, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    _revoke_all_user_tokens(db, user)


STALE_TOKEN_RETENTION_DAYS = 30


def _sweep_expired_tokens(db: Session, user_id: str) -> None:
    now = utcnow()
    cutoff = now - timedelta(days=STALE_TOKEN_RETENTION_DAYS)

    active_but_expired = db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.status == "active",
            RefreshToken.expires_at <= now,
        )
    ).all()
    for rt in active_but_expired:
        _revoke_refresh_token(rt, status_value="revoked")

    db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.isnot(None),
            RefreshToken.revoked_at <= cutoff,
        )
    )

    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.expires_at <= now,
        )
    )

    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.status == "used",
        )
    )


def _session_user_response(user: User, access_token: str) -> dict:
    profile = user.profile
    user_settings = user.settings
    return {
        "user_id": user.id,
        "access_token": access_token,
        "token_type": "Bearer",
        "username": user.username,
        "email": user.email,
        "nickname": profile.nickname if profile else "",
        "age_range": profile.age_range if profile else "",
        "user_mode": _profile_user_mode(user),
        "usage_goals": list(profile.usage_goals or []) if profile else [],
        "onboarding_completed": _profile_onboarding_completed(user),
        "memory_mode": user_settings.memory_mode if user_settings else "summary_only",
        "companion_style": normalize_custom_companion_style(user_settings.companion_style) if user_settings else "",
    }


def _read_refresh_token_from_cookie(rt: str | None) -> str:
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期，请重新登录。",
        )
    return rt


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    return _as_utc_aware(expires_at) <= _as_utc_aware(now or utcnow())


@router.get("/captcha", response_model=CaptchaResponse)
async def captcha() -> CaptchaResponse:
    return CaptchaResponse(**captcha_store.create())


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db_session),
) -> Response:
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
        security_question=payload.security_question.strip(),
        security_answer_hash=hash_password(payload.security_answer.strip()),
    )
    user_settings = UserSettings(
        user_id=user.id,
        memory_mode="summary_only",
        companion_style="",
        crisis_resource_region="CN",
    )
    db.add_all([user, profile, user_settings])
    db.flush()
    access_token, refresh_token = _issue_token_pair(db, user, auto_login=False)
    db.commit()
    db.refresh(user)

    response_body = _session_user_response(user, access_token)
    response = Response(
        content=RegisterResponse(**response_body).model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED,
    )
    _set_refresh_cookie(response, refresh_token, auto_login=False)
    return response


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> Response:
    _verify_captcha(payload.captcha_id, payload.captcha_code)
    username = _normalize_username(payload.username)
    client_ip = request.client.host if request.client else "unknown"

    blocked, block_reason = login_attempt_store.is_blocked(client_ip, username)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=block_reason,
        )

    user = db.scalar(select(User).options(selectinload(User.profile), selectinload(User.settings)).where(User.username == username, User.status == "active"))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_attempt_store.record_failure(client_ip, username, "invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )

    login_attempt_store.clear(client_ip, username)
    access_token, refresh_token = _issue_token_pair(db, user, auto_login=payload.auto_login)
    db.commit()
    db.refresh(user)
    response_body = _session_user_response(user, access_token)
    response = Response(
        content=LoginResponse(**response_body).model_dump_json(),
        media_type="application/json",
    )
    _set_refresh_cookie(response, refresh_token, auto_login=payload.auto_login)
    return response

@router.post("/dev-session", response_model=LoginResponse)
async def dev_session(
    request: Request,
    db: Session = Depends(get_db_session),
) -> Response:
    if not _is_dev_session_allowed(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    user = _ensure_dev_session_user(db)
    access_token, refresh_token = _issue_token_pair(db, user, auto_login=False)
    db.commit()
    db.refresh(user)
    response_body = _session_user_response(user, access_token)
    response = Response(
        content=LoginResponse(**response_body).model_dump_json(),
        media_type="application/json",
    )
    _set_refresh_cookie(response, refresh_token, auto_login=False)
    return response


@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: Session = Depends(get_db_session),
) -> Response:
    refresh_token_str = _read_refresh_token_from_cookie(request.cookies.get(REFRESH_COOKIE_KEY))
    token_record, user = _validate_refresh_token(db, refresh_token_str)

    access_token, next_refresh_token = _issue_token_pair(db, user, auto_login=token_record.auto_login)
    _revoke_refresh_token(token_record, status_value="rotated")
    db.commit()

    response_body = _session_user_response(user, access_token)
    response = Response(
        content=RefreshTokenResponse(**response_body).model_dump_json(),
        media_type="application/json",
    )
    _set_refresh_cookie(response, next_refresh_token, auto_login=token_record.auto_login)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: Session = Depends(get_db_session),
) -> Response:
    rt = request.cookies.get(REFRESH_COOKIE_KEY)
    if rt:
        try:
            token_record, _ = _validate_refresh_token(db, rt)
            _revoke_refresh_token(token_record, status_value="revoked")
            db.commit()
        except HTTPException:
            pass
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    profile = current_user.profile
    user_settings = current_user.settings
    if profile is None or user_settings is None:
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
        memory_mode=user_settings.memory_mode,
        companion_style=normalize_custom_companion_style(user_settings.companion_style),
    )


@router.get("/password-reset-question", response_model=PasswordResetQuestionResponse)
async def password_reset_question(
    username: str = Query(min_length=3, max_length=24, pattern=USERNAME_PATTERN),
    db: Session = Depends(get_db_session),
) -> PasswordResetQuestionResponse:
    normalized = _normalize_username(username)
    user = db.scalar(
        select(User).options(selectinload(User.profile)).where(User.username == normalized, User.status == "active")
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户名不存在。",
        )
    if user.profile is None or not user.profile.security_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该账号未设置密保问题，无法找回密码。",
        )
    return PasswordResetQuestionResponse(
        username=normalized,
        security_question=user.profile.security_question,
    )


@router.post("/password-reset-verify", response_model=PasswordResetVerifyResponse)
async def password_reset_verify(
    payload: PasswordResetVerifyRequest,
    db: Session = Depends(get_db_session),
) -> PasswordResetVerifyResponse:
    username = _normalize_username(payload.username)
    user = db.scalar(
        select(User).options(selectinload(User.profile)).where(User.username == username, User.status == "active")
    )
    if user is None or user.profile is None or not user.profile.security_answer_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密保问题未设置。",
        )

    if not verify_password(payload.answer.strip(), user.profile.security_answer_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密保答案错误。",
        )

    token_id = str(uuid4())
    raw_token = create_token(user.id, "password_reset", RESET_TOKEN_TTL_SECONDS, token_id=token_id)
    db.add(
        PasswordResetToken(
            id=token_id,
            user_id=user.id,
            token_hash=hash_token(raw_token),
            status="active",
            expires_at=utcnow() + timedelta(seconds=RESET_TOKEN_TTL_SECONDS),
        )
    )
    db.commit()
    return PasswordResetVerifyResponse(reset_token=raw_token)


@router.post("/password-reset")
async def password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        token_payload = decode_token(payload.reset_token, expected_type="password_reset")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期。") from exc

    token_id = token_payload.get("jti")
    if not token_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的重置令牌。")

    reset_record = db.scalar(select(PasswordResetToken).where(PasswordResetToken.id == token_id))
    if reset_record is None or reset_record.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期。")
    if _is_expired(reset_record.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期。")

    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    user = db.scalar(select(User).where(User.id == token_payload["sub"], User.status == "active"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户不存在。")

    _rotate_password(db, user, payload.new_password)
    reset_record.status = "used"
    reset_record.used_at = utcnow()

    db.commit()
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Response:
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码错误。",
        )

    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    user = db.scalar(
        select(User).options(selectinload(User.profile), selectinload(User.settings)).where(
            User.id == current_user.id, User.status == "active"
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")

    _rotate_password(db, user, payload.new_password)

    access_token, refresh_token = _issue_token_pair(db, user, auto_login=False)
    db.commit()
    db.refresh(user)

    response_body = _session_user_response(user, access_token)
    response = Response(
        content=ChangePasswordResponse(**response_body).model_dump_json(),
        media_type="application/json",
    )
    _set_refresh_cookie(response, refresh_token, auto_login=False)
    return response
