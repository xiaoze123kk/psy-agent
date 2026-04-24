from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    age_range: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
async def register(payload: RegisterRequest) -> dict[str, str | bool]:
    user_mode = "teen" if payload.age_range in {"13_15", "16_17"} else "adult"
    return {
        "user_id": str(uuid4()),
        "access_token": "replace-with-real-jwt",
        "refresh_token": "replace-with-real-refresh-token",
        "user_mode": user_mode,
        "onboarding_completed": False,
    }


@router.post("/login")
async def login(_: LoginRequest) -> dict[str, str]:
    return {
        "access_token": "replace-with-real-jwt",
        "refresh_token": "replace-with-real-refresh-token",
    }


@router.get("/me")
async def me() -> dict[str, str]:
    return {
        "user_id": "demo-user",
        "nickname": "demo",
        "user_mode": "adult",
    }
