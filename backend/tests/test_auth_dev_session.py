from __future__ import annotations

import unittest
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth
from app.db.models import Base, User
from app.db.session import get_db_session


class AuthDevSessionTests(unittest.TestCase):
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
        self.original_settings = auth.settings

    def tearDown(self) -> None:
        auth.settings = self.original_settings
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_dev_session_issues_tokens_for_local_default_dev_secret(self) -> None:
        auth.settings = replace(
            self.original_settings,
            secret_key="dev-only-change-me",
            database_url="postgresql+psycopg://postgres:123456@127.0.0.1:5432/psychology_agent",
        )

        response = self.client.post("/api/v1/auth/dev-session")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertTrue(payload["access_token"])
        self.assertTrue(payload["refresh_token"])
        self.assertEqual(payload["user_mode"], "adult")
        self.assertTrue(payload["onboarding_completed"])
        user = self.db.scalar(select(User).where(User.username == "local_debug_user"))
        self.assertIsNotNone(user)

        me_response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )

        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["username"], "local_debug_user")

    def test_dev_session_is_disabled_when_secret_is_not_default_dev_secret(self) -> None:
        auth.settings = replace(self.original_settings, secret_key="production-secret")

        response = self.client.post("/api/v1/auth/dev-session")

        self.assertEqual(response.status_code, 404)
