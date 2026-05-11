from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import mood
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, MoodLog, User
from app.db.session import get_db_session


class WeeklySummaryApiTests(unittest.TestCase):
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
        self.app.include_router(mood.router, prefix="/api/v1")

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

    def add_log(
        self,
        user: User,
        *,
        mood_score: int,
        days_ago: int,
        mood_tags: list[str] | None = None,
    ) -> MoodLog:
        log = MoodLog(
            user_id=user.id,
            mood_score=mood_score,
            mood_tags=mood_tags or [],
            source="checkin",
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def test_weekly_summary_no_data_returns_fallback(self) -> None:
        user = self.create_user()

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("range", body)
        self.assertTrue(body["summary"])
        self.assertEqual(body["generated_by"], "fallback")

    def test_weekly_summary_with_7_days_data(self) -> None:
        user = self.create_user()

        for i in range(7):
            self.add_log(user, mood_score=4, days_ago=i, mood_tags=["平静"])

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("range", body)
        self.assertTrue(body["summary"])
        self.assertIn("top_tags", body)
        self.assertIn("suggested_actions", body)
        self.assertIn("generated_by", body)

    def test_weekly_summary_aggregates_tags(self) -> None:
        user = self.create_user()

        self.add_log(user, mood_score=3, days_ago=0, mood_tags=["焦虑", "疲惫"])
        self.add_log(user, mood_score=4, days_ago=1, mood_tags=["焦虑", "平静"])
        self.add_log(user, mood_score=2, days_ago=2, mood_tags=["焦虑", "难过"])

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("焦虑", body["top_tags"])

    def test_weekly_summary_requires_auth(self) -> None:
        response = self.client.get("/api/v1/moods/weekly-summary")

        self.assertEqual(response.status_code, 401)

    def test_weekly_summary_does_not_contain_diagnostic_terms(self) -> None:
        user = self.create_user()

        self.add_log(user, mood_score=1, days_ago=0, mood_tags=["难过", "空虚"])

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        summary_text = body["summary"].lower()
        forbidden = ["诊断", "确诊", "病情", "治疗", "障碍", "症状", "药"]
        for term in forbidden:
            self.assertNotIn(term, summary_text, f"summary should not contain '{term}'")

    def test_weekly_summary_generated_by_field_is_valid(self) -> None:
        user = self.create_user()

        self.add_log(user, mood_score=2, days_ago=0, mood_tags=["压力"])

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["generated_by"], {"llm", "fallback"})

    def add_thread(
        self,
        user: User,
        *,
        last_summary: str,
        days_ago: int = 0,
    ) -> ConversationThread:
        thread = ConversationThread(
            user_id=user.id,
            langgraph_thread_id=f"test-thread-{days_ago}-{id(self)}",
            last_summary=last_summary,
            updated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(thread)
        return thread

    def test_weekly_summary_with_moods_and_threads(self) -> None:
        user = self.create_user()

        for i in range(5):
            self.add_log(user, mood_score=3, days_ago=i, mood_tags=["焦虑"])
        self.add_thread(user, last_summary="最近和室友的关系让用户感到疲惫", days_ago=1)
        self.add_thread(user, last_summary="用户在考虑是否换一个专业方向", days_ago=3)

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["summary"])
        self.assertIn("焦虑", body["top_tags"])
        self.assertIn("generated_by", body)
        self.assertTrue(len(body["suggested_actions"]) > 0)

    def test_weekly_summary_no_moods_but_had_conversations(self) -> None:
        user = self.create_user()

        self.add_thread(user, last_summary="用户分享了最近的失眠经历", days_ago=0)

        response = self.client.get(
            "/api/v1/moods/weekly-summary",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["generated_by"], "fallback")
        self.assertIn("对话", body["summary"])


if __name__ == "__main__":
    unittest.main()
