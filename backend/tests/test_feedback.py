from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import feedback
from app.core.security import create_access_token
from app.db.models import Base, User
from app.db.session import get_db_session


class FeedbackApiTests(unittest.TestCase):
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
        self.app.include_router(feedback.router, prefix="/api/v1")

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

    def test_submit_feedback_assistant_message(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "target_id": "msg-abc-123",
                "rating": 5,
                "tags": ["有帮助", "温暖"],
                "note": "回复很贴心",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "recorded")
        self.assertTrue(body["feedback_id"])

    def test_submit_feedback_knowledge_answer(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "knowledge_answer",
                "target_id": "knowledge-msg-001",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recorded")

    def test_submit_feedback_test_result(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "test_result",
                "target_id": "attempt-xyz-456",
                "rating": 4,
                "tags": ["有趣"],
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_submit_feedback_rejects_invalid_rating_low(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "rating": 0,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_rejects_invalid_rating_high(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "rating": 6,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_rejects_invalid_target_type(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "invalid_type",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_requires_auth(self) -> None:
        response = self.client.post(
            "/api/v1/feedback",
            json={
                "target_type": "assistant_message",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_submit_feedback_without_note(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "target_id": "msg-test-001",
                "rating": 2,
                "tags": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
