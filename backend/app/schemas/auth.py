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
    password: str = Field(min_length=8)
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8)
    age_range: AgeRange
    security_question: str = Field(min_length=1, max_length=200)
    security_answer: str = Field(min_length=1, max_length=200)
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)


class RegisterResponse(BaseModel):
    user_id: str
    access_token: str
    token_type: str = "Bearer"
    user_mode: UserMode
    onboarding_completed: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=6)
    captcha_id: str
    captcha_code: str = Field(min_length=4, max_length=8)
    auto_login: bool = False


class LoginResponse(BaseModel):
    user_id: str
    access_token: str
    token_type: str = "Bearer"
    user_mode: UserMode
    onboarding_completed: bool


class RefreshTokenRequest(BaseModel):
    pass


class RefreshTokenResponse(BaseModel):
    user_id: str
    access_token: str
    token_type: str = "Bearer"
    user_mode: UserMode
    onboarding_completed: bool


class LogoutRequest(BaseModel):
    pass


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


class PasswordResetQuestionRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)


class PasswordResetQuestionResponse(BaseModel):
    username: str
    security_question: str


class PasswordResetVerifyRequest(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=USERNAME_PATTERN)
    answer: str = Field(min_length=1, max_length=200)


class PasswordResetVerifyResponse(BaseModel):
    reset_token: str


class PasswordResetRequest(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=8)
