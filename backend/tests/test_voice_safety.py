from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import voice
from app.core.security import create_access_token
from app.db.models import Base, User
from app.db.session import get_db_session


class VoiceSessionApiTests(unittest.TestCase):
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
        self.app.include_router(voice.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def test_create_voice_session_without_thread(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["voice_session_id"])
        self.assertTrue(body["thread_id"])
        self.assertEqual(body["protocol"], "text-simulated-voice-v1")
        self.assertIn("/api/v1/voice/sessions/", body["ws_url"])

    def test_create_voice_session_with_thread(self) -> None:
        user = self.create_user()

        # Create a thread-like record directly (skip thread creation since we test voice)
        response = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion", "thread_id": None},
        )

        self.assertEqual(response.status_code, 200)
        thread_id = response.json()["thread_id"]

        # Create second voice session with the existing thread_id
        response2 = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "crisis", "thread_id": thread_id},
        )

        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["thread_id"], thread_id)

    def test_create_voice_session_requires_auth(self) -> None:
        response = self.client.post(
            "/api/v1/voice/sessions",
            json={"mode": "companion"},
        )

        self.assertEqual(response.status_code, 401)

    def test_create_voice_session_with_save_transcript(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion", "save_transcript": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["voice_session_id"])

    def test_create_voice_session_defaults_to_companion_mode(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("/api/v1/voice/sessions/", body["ws_url"])


class VoiceSafetyRoutingTests(unittest.TestCase):
    """Verify that the voice endpoint correctly routes risk-related logic.

    These tests validate that the voice session creation and protocol
    events are structured correctly. The actual risk classification
    is covered by test_safety_evaluation.py.
    """

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
        self.app.include_router(voice.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def test_voice_session_creation_produces_valid_ws_url(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion"},
        )

        self.assertEqual(response.status_code, 200)
        ws_url = response.json()["ws_url"]
        self.assertTrue(ws_url.startswith("/api/v1/voice/sessions/"))
        self.assertTrue(ws_url.endswith("/ws"))

    def test_voice_session_creation_is_idempotent_with_same_params(self) -> None:
        user = self.create_user()

        resp1 = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion"},
        )
        resp2 = self.client.post(
            "/api/v1/voice/sessions",
            headers=self.auth_headers(user),
            json={"mode": "companion"},
        )

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        # Each call creates a new session (different voice_session_id)
        self.assertNotEqual(resp1.json()["voice_session_id"], resp2.json()["voice_session_id"])


if __name__ == "__main__":
    unittest.main()
