from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, UserMemory, UserProfile, UserSettings
from app.services.user_context_service import build_goal_state, build_user_profile_digest


class UserContextServiceTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(
        self,
        username: str = "demo",
        *,
        usage_goals: list[str] | None = None,
        companion_style: str = "先短短安抚我，再给一个小步骤",
    ) -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname="小林",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=usage_goals or ["先安抚再建议"],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode="long_term",
                    companion_style=companion_style,
                    voice_enabled=False,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_memory(self, user: User, *, memory_type: str, content: str) -> UserMemory:
        memory = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            title=f"{memory_type}: {content[:24]}",
            summary=content,
            content=content,
            visibility="user_visible",
            status="active",
            review_state="normal",
        )
        self.db.add(memory)
        self.db.commit()
        return memory

    def test_build_user_profile_digest_combines_profile_settings_and_memory_hints(self) -> None:
        user = self.create_user()
        self.add_memory(user, memory_type="profile", content="用户遇到压力时习惯先沉默一会儿")
        self.add_memory(user, memory_type="preference", content="用户不喜欢一上来就连环追问")

        digest = build_user_profile_digest(self.db, user_id=user.id)

        self.assertIsNotNone(digest)
        self.assertEqual(digest["nickname"], "小林")
        self.assertEqual(digest["age_range"], "18_plus")
        self.assertEqual(digest["user_mode"], "adult")
        self.assertEqual(digest["usage_goals"], ["先安抚再建议"])
        self.assertTrue(any("先短短安抚我" in item for item in digest["communication_preferences"]))
        self.assertIn("用户遇到压力时习惯先沉默一会儿", digest["profile_hints"])
        self.assertIn("用户不喜欢一上来就连环追问", digest["preference_hints"])
        self.assertEqual(digest["correction_hints"], [])

    def test_build_goal_state_binds_previous_clarification_answer(self) -> None:
        user = self.create_user()

        goal_state = build_goal_state(
            self.db,
            user_id=user.id,
            current_text="主管那件事",
            recent_messages=[
                {
                    "role": "assistant",
                    "content": "我先确认一下：你想从具体发生的事说起，还是先说现在的感觉？",
                    "metadata": {
                        "clarification_needed": True,
                        "clarification_reason": "vague_without_context",
                        "control_category": "clarification_needed",
                    },
                }
            ],
        )

        self.assertIsNotNone(goal_state)
        self.assertEqual(goal_state["clarification_answer"], "主管那件事")
        self.assertEqual(goal_state["clarification_reason"], "vague_without_context")
        self.assertIn("主管那件事", goal_state["current_goal"])


if __name__ == "__main__":
    unittest.main()
