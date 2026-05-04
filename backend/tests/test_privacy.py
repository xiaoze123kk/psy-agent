from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth, me, privacy
from app.core.security import create_access_token, create_refresh_token, hash_token
from app.db.models import (
    Base,
    ConversationThread,
    Message,
    MoodLog,
    RefreshToken,
    TestHistory,
    User,
    UserFeedback,
    UserMemory,
    UserProfile,
    UserSettings,
    VoiceSession,
    utcnow,
)
from app.db.session import get_db_session


class PrivacyApiTests(unittest.TestCase):
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
        self.app.include_router(me.router, prefix="/api/v1")
        self.app.include_router(privacy.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo", *, user_mode: str = "adult") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname=username,
                    age_range="16_17" if user_mode == "teen" else "18_plus",
                    user_mode=user_mode,
                    usage_goals=["heard"],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode="summary_only",
                    companion_style="gentle",
                    voice_enabled=True,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def seed_private_data(self, user: User) -> dict[str, object]:
        thread = ConversationThread(user_id=user.id, langgraph_thread_id=f"lg-{user.username}", title="隐私测试")
        self.db.add(thread)
        self.db.flush()
        message = Message(thread_id=thread.id, user_id=user.id, role="user", content="只属于我的消息")
        memory = UserMemory(user_id=user.id, memory_type="session_summary", content="只属于我的记忆")
        mood = MoodLog(user_id=user.id, mood_score=3, mood_tags=["平静"], source="checkin")
        history = TestHistory(
            user_id=user.id,
            attempt_id="00000000-0000-0000-0000-000000000001",
            test_id="state-check-v1",
            test_title="今日状态测试",
            result_code="stable",
            result_label="当前状态较稳定",
            completed_at=utcnow(),
        )
        feedback = UserFeedback(user_id=user.id, target_type="assistant_message", target_id="msg-1", rating=4)
        voice_session = VoiceSession(user_id=user.id, thread_id=thread.id, mode="companion", save_transcript=True)
        self.db.add_all([message, memory, mood, history, feedback, voice_session])
        self.db.commit()
        return {
            "thread": thread,
            "message": message,
            "memory": memory,
            "mood": mood,
            "history": history,
            "feedback": feedback,
            "voice_session": voice_session,
        }

    def test_privacy_summary_counts_current_user_data(self) -> None:
        user = self.create_user("owner")
        other = self.create_user("other")
        self.seed_private_data(user)
        self.seed_private_data(other)

        response = self.client.get("/api/v1/me/privacy-summary", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        counts = response.json()["data_counts"]
        self.assertEqual(counts["memories"], 1)
        self.assertEqual(counts["chat_threads"], 1)
        self.assertEqual(counts["chat_messages"], 1)
        self.assertEqual(counts["mood_logs"], 1)
        self.assertEqual(counts["test_history"], 1)
        self.assertEqual(counts["feedback"], 1)
        self.assertEqual(counts["voice_sessions"], 1)

    def test_data_export_excludes_other_users_and_sensitive_auth_fields(self) -> None:
        user = self.create_user("owner")
        other = self.create_user("other")
        self.seed_private_data(user)
        self.seed_private_data(other)

        response = self.client.get("/api/v1/me/data-export?format=json", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["account"]["username"], "owner")
        self.assertNotIn("password_hash", body["account"])
        self.assertNotIn("refresh_token", str(body))
        self.assertEqual(body["chat_threads"][0]["messages"][0]["content"], "只属于我的消息")
        self.assertTrue(all(thread["thread_id"] != other.id for thread in body["chat_threads"]))

    def test_delete_scope_does_not_affect_other_users(self) -> None:
        user = self.create_user("owner")
        other = self.create_user("other")
        own = self.seed_private_data(user)
        other_data = self.seed_private_data(other)
        own_mood_id = own["mood"].id
        other_mood_id = other_data["mood"].id

        response = self.client.request(
            "DELETE",
            "/api/v1/me/data",
            headers=self.auth_headers(user),
            json={"scope": "moods"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["affected_counts"]["mood_logs"], 1)
        self.assertIsNone(self.db.get(MoodLog, own_mood_id))
        self.assertIsNotNone(self.db.get(MoodLog, other_mood_id))

    def test_delete_all_non_account_clears_user_data_but_keeps_account(self) -> None:
        user = self.create_user("owner")
        self.seed_private_data(user)

        response = self.client.request(
            "DELETE",
            "/api/v1/me/data",
            headers=self.auth_headers(user),
            json={"scope": "all_non_account"},
        )
        self.db.refresh(user)
        archived_threads = list(self.db.scalars(select(ConversationThread).where(ConversationThread.user_id == user.id)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.status, "active")
        self.assertEqual(len(list(self.db.scalars(select(Message).where(Message.user_id == user.id)))), 0)
        self.assertTrue(all(thread.archived_at is not None for thread in archived_threads))
        self.assertEqual(len(list(self.db.scalars(select(MoodLog).where(MoodLog.user_id == user.id)))), 0)
        self.assertEqual(len(list(self.db.scalars(select(TestHistory).where(TestHistory.user_id == user.id)))), 0)

    def test_delete_account_revokes_tokens_and_blocks_current_user(self) -> None:
        user = self.create_user("owner")
        self.seed_private_data(user)
        refresh_token = create_refresh_token(user.id, token_id="00000000-0000-0000-0000-000000000099")
        self.db.add(
            RefreshToken(
                id="00000000-0000-0000-0000-000000000099",
                user_id=user.id,
                token_hash=hash_token(refresh_token),
                status="active",
                expires_at=utcnow(),
            )
        )
        self.db.commit()
        headers = self.auth_headers(user)

        response = self.client.request(
            "DELETE",
            "/api/v1/me/account",
            headers=headers,
            json={"confirmation": "DELETE"},
        )
        me_response = self.client.get("/api/v1/auth/me", headers=headers)
        self.db.refresh(user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.status, "deleted")
        self.assertIsNotNone(user.deleted_at)
        self.assertEqual(me_response.status_code, 401)
        token = self.db.get(RefreshToken, "00000000-0000-0000-0000-000000000099")
        self.assertEqual(token.status, "revoked")

    def test_teen_mode_rejects_save_voice_audio(self) -> None:
        teen = self.create_user("teenuser", user_mode="teen")

        response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(teen),
            json={"save_voice_audio": True},
        )
        self.db.refresh(teen.settings)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(teen.settings.save_voice_audio)

    def test_settings_can_update_save_transcript(self) -> None:
        user = self.create_user("owner")

        response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(user),
            json={"save_transcript": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["save_transcript"])


if __name__ == "__main__":
    unittest.main()
