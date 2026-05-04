from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import AgeRange, MemoryMode, UserMode


USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,24}$"


class CaptchaResponse(BaseModel):
    captcha_id: str
    image_data_url: str
    expires_in: int


class CaptchaProtectedRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=6)
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=6)
    age_range: AgeRange
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)


class RegisterResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    access_expires_in: int
    refresh_expires_in: int
    user_mode: UserMode
    onboarding_completed: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=6)
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)


class LoginResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    access_expires_in: int
    refresh_expires_in: int
    user_mode: UserMode
    onboarding_completed: bool


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    access_expires_in: int
    refresh_expires_in: int


class LogoutRequest(BaseModel):
    refresh_token: str


class CurrentUserResponse(BaseModel):
    user_id: str
    username: str
    email: str | None = None
    nickname: str
    age_range: str
    user_mode: UserMode
    usage_goals: list[str]
    onboarding_completed: bool
    memory_mode: MemoryMode
    companion_style: str
    voice_enabled: bool
    save_voice_audio: bool
