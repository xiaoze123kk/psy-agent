from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import mood
from app.core.security import create_access_token
from app.db.models import Base, MoodLog, User
from app.db.session import get_db_session


class MoodApiTests(unittest.TestCase):
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

    def test_create_mood_log_persists_checkin_fields(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/moods",
            headers=self.auth_headers(user),
            json={
                "mood_score": 2,
                "anxiety_score": 4,
                "energy_score": 2,
                "sleep_quality": 3,
                "mood_tags": ["焦虑", "疲惫"],
                "note": "今天临近考试，整个人很紧绷",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mood_score"], 2)
        self.assertTrue(body["log_id"])
        self.assertTrue(body["created_at"])

        log = self.db.scalar(select(MoodLog).where(MoodLog.id == body["log_id"]))
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.user_id, user.id)
        self.assertEqual(log.anxiety_score, 4)
        self.assertEqual(log.energy_score, 2)
        self.assertEqual(log.sleep_quality, 3)
        self.assertEqual(log.mood_tags, ["焦虑", "疲惫"])
        self.assertEqual(log.note, "今天临近考试，整个人很紧绷")
        self.assertEqual(log.source, "checkin")

    def test_create_mood_log_rejects_invalid_score(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/moods",
            headers=self.auth_headers(user),
            json={"mood_score": 6},
        )

        self.assertEqual(response.status_code, 422)

    def test_create_mood_log_requires_auth(self) -> None:
        response = self.client.post("/api/v1/moods", json={"mood_score": 3})

        self.assertEqual(response.status_code, 401)

    def test_trend_returns_empty_state_for_user_without_logs(self) -> None:
        user = self.create_user()

        response = self.client.get("/api/v1/moods/trends?range=7d", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "range": "7d",
                "avg_mood_score": 0,
                "top_tags": [],
                "daily": [],
                "summary": "当前时间范围内还没有情绪记录。",
            },
        )

    def test_trend_filters_by_range_and_user_and_counts_top_tags(self) -> None:
        user = self.create_user("owner")
        other_user = self.create_user("other")
        recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

        self.add_log(user, mood_score=2, days_ago=1, mood_tags=["焦虑", "疲惫"])
        self.add_log(user, mood_score=4, days_ago=1, mood_tags=["焦虑", "疲惫", " "])
        self.add_log(user, mood_score=5, days_ago=10, mood_tags=["平静"])
        self.add_log(user, mood_score=1, days_ago=40, mood_tags=["旧记录"])
        self.add_log(other_user, mood_score=1, days_ago=1, mood_tags=["他人"])

        response_7d = self.client.get("/api/v1/moods/trends?range=7d", headers=self.auth_headers(user))
        self.assertEqual(response_7d.status_code, 200)
        body_7d = response_7d.json()
        self.assertEqual(body_7d["range"], "7d")
        self.assertEqual(body_7d["avg_mood_score"], 3)
        self.assertEqual(body_7d["top_tags"], ["焦虑", "疲惫"])
        self.assertEqual(body_7d["daily"], [{"date": recent_date, "mood_score": 3, "tags": ["焦虑", "疲惫"]}])
        self.assertIn("最近 7 天共记录 2 次情绪", body_7d["summary"])

        response_30d = self.client.get("/api/v1/moods/trends?range=30d", headers=self.auth_headers(user))
        self.assertEqual(response_30d.status_code, 200)
        body_30d = response_30d.json()
        self.assertEqual(body_30d["range"], "30d")
        self.assertEqual(body_30d["avg_mood_score"], 3.67)
        self.assertEqual(body_30d["top_tags"], ["焦虑", "疲惫", "平静"])
        self.assertEqual(len(body_30d["daily"]), 2)

    def test_trend_rejects_invalid_range(self) -> None:
        user = self.create_user()

        response = self.client.get("/api/v1/moods/trends?range=14d", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
