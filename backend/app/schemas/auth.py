from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import AgeRange, UserMode


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)
    age_range: AgeRange


class RegisterResponse(BaseModel):
    user_id: str
    access_token: str
    refresh_token: str
    user_mode: UserMode
    onboarding_completed: bool


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str


class CurrentUserResponse(BaseModel):
    user_id: str
    email: str
    nickname: str
    age_range: str
    user_mode: UserMode
    usage_goals: list[str]
    onboarding_completed: bool
    memory_mode: str
    companion_style: str
    voice_enabled: bool
