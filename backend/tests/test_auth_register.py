from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth
from app.db.models import Base, PasswordResetToken, RefreshToken, User, UserProfile
from app.db.session import get_db_session


class AuthRegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, class_=Session)
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(auth.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_register_flushes_user_before_issuing_refresh_token(self) -> None:
        payload = {
            "username": "new_user",
            "password": "Password123",
            "age_range": "18_plus",
            "security_question": "first pet",
            "security_answer": "not-secret-test",
            "captcha_id": "captcha-id",
            "captcha_code": "ABCDE",
        }

        with patch.object(auth, "_verify_captcha", return_value=None):
            response = self.client.post("/api/v1/auth/register", json=payload)

        self.assertEqual(response.status_code, 201)
        user = self.db.scalar(select(User).where(User.username == "new_user"))
        self.assertIsNotNone(user)
        self.assertIsNotNone(self.db.scalar(select(UserProfile).where(UserProfile.user_id == user.id)))
        self.assertIsNotNone(self.db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id)))

    def test_login_returns_session_payload_and_refresh_cookie(self) -> None:
        with patch.object(auth, "_verify_captcha", return_value=None):
            self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": "login_user",
                    "password": "Password123",
                    "age_range": "18_plus",
                    "security_question": "first pet",
                    "security_answer": "not-secret-test",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCDE",
                },
            )
            response = self.client.post(
                "/api/v1/auth/login",
                json={
                    "username": "login_user",
                    "password": "Password123",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCDE",
                    "auto_login": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["username"], "login_user")
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertTrue(payload["access_token"])
        self.assertIn("rt=", response.headers.get("set-cookie", ""))

    def test_refresh_accepts_timezone_aware_expiry(self) -> None:
        with patch.object(auth, "_verify_captcha", return_value=None):
            register_response = self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": "refresh_user",
                    "password": "Password123",
                    "age_range": "18_plus",
                    "security_question": "first pet",
                    "security_answer": "not-secret-test",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCDE",
                },
            )

        self.assertEqual(register_response.status_code, 201)
        user = self.db.scalar(select(User).where(User.username == "refresh_user"))
        refresh_token = self.db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
        refresh_token.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        response = self.client.post("/api/v1/auth/refresh")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "refresh_user")

    def test_password_reset_accepts_timezone_aware_expiry(self) -> None:
        with patch.object(auth, "_verify_captcha", return_value=None):
            register_response = self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": "reset_user",
                    "password": "Password123",
                    "age_range": "18_plus",
                    "security_question": "first pet",
                    "security_answer": "not-secret-test",
                    "captcha_id": "captcha-id",
                    "captcha_code": "ABCDE",
                },
            )

        self.assertEqual(register_response.status_code, 201)
        verify_response = self.client.post(
            "/api/v1/auth/password-reset-verify",
            json={
                "username": "reset_user",
                "answer": "not-secret-test",
            },
        )
        self.assertEqual(verify_response.status_code, 200)

        reset_record = self.db.scalar(select(PasswordResetToken).where(PasswordResetToken.status == "active"))
        reset_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        response = self.client.post(
            "/api/v1/auth/password-reset",
            json={
                "reset_token": verify_response.json()["reset_token"],
                "new_password": "Newpass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
