from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth
from app.core.security import hash_password
from app.db.models import Base, RefreshToken, User, UserProfile, UserSettings
from app.db.session import get_db_session


class AuthRegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, class_=Session)
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(auth.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_register_flushes_user_before_issuing_refresh_token(self) -> None:
        def issue_token_pair(db: Session, user, auto_login: bool) -> tuple[str, str]:
            self.assertTrue(inspect(user).persistent)
            return "access-token", "refresh-token"

        with patch.object(auth, "_verify_captcha", return_value=None), patch.object(
            auth,
            "_issue_token_pair",
            side_effect=issue_token_pair,
        ):
            response = self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": "reguser",
                    "password": "Aa123456!",
                    "age_range": "16_17",
                    "security_question": "第一只宠物叫什么",
                    "security_answer": "mimi",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCD",
                },
            )

        self.assertEqual(response.status_code, 201)

    def test_login_returns_session_response_after_successful_credentials(self) -> None:
        user_id = str(uuid4())
        self.db.add_all(
            [
                User(
                    id=user_id,
                    username="loginuser",
                    email="loginuser@local.invalid",
                    password_hash=hash_password("Aa123456!"),
                ),
                UserProfile(
                    user_id=user_id,
                    nickname="登录用户",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user_id,
                    memory_mode="summary_only",
                    companion_style="",
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()

        with patch.object(auth, "_verify_captcha", return_value=None):
            response = self.client.post(
                "/api/v1/auth/login",
                json={
                    "username": "loginuser",
                    "password": "Aa123456!",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCD",
                    "auto_login": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["username"], "loginuser")
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertTrue(payload["access_token"])
        self.assertIn("rt=", response.headers.get("set-cookie", ""))

    def test_refresh_validation_accepts_timezone_aware_expiration_from_database(self) -> None:
        user_id = str(uuid4())
        user = User(
            id=user_id,
            username="refreshuser",
            email="refreshuser@local.invalid",
            password_hash=hash_password("Aa123456!"),
        )
        self.db.add_all(
            [
                user,
                UserProfile(
                    user_id=user_id,
                    nickname="刷新用户",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user_id,
                    memory_mode="summary_only",
                    companion_style="",
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.flush()
        _, refresh_token = auth._issue_token_pair(self.db, user, auto_login=True)
        self.db.flush()
        token_record = self.db.scalar(select(RefreshToken).where(RefreshToken.user_id == user_id))
        self.assertIsNotNone(token_record)
        token_record.expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        validated_record, validated_user = auth._validate_refresh_token(self.db, refresh_token)

        self.assertEqual(validated_record.id, token_record.id)
        self.assertEqual(validated_user.username, "refreshuser")
