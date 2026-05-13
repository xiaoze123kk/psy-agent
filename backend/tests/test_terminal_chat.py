from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ConversationThread, Message
from app.db.models import utcnow
from scripts import terminal_chat


class TerminalChatTests(unittest.TestCase):
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

    def test_ensure_terminal_user_creates_standard_profile_and_settings(self) -> None:
        with patch("scripts.terminal_chat.hash_password", return_value="hashed-password"):
            user = terminal_chat.ensure_terminal_user(self.db)

        self.assertEqual(user.username, "terminal_user")
        self.assertIsNotNone(user.profile)
        self.assertIsNotNone(user.settings)
        self.assertEqual(user.profile.nickname, "Terminal")
        self.assertEqual(user.profile.age_range, "18_plus")
        self.assertEqual(user.profile.user_mode, "adult")
        self.assertTrue(user.profile.onboarding_completed)
        self.assertEqual(user.settings.memory_mode, "summary_only")
        self.assertEqual(user.settings.companion_style, "")

    def test_ensure_terminal_thread_reuses_latest_matching_thread(self) -> None:
        with patch("scripts.terminal_chat.hash_password", return_value="hashed-password"):
            user = terminal_chat.ensure_terminal_user(self.db)

        first_thread = terminal_chat.ensure_terminal_thread(self.db, user=user)
        reused_thread = terminal_chat.ensure_terminal_thread(self.db, user=user)
        fresh_thread = terminal_chat.ensure_terminal_thread(self.db, user=user, create_new=True)

        self.assertEqual(first_thread.id, reused_thread.id)
        self.assertNotEqual(first_thread.id, fresh_thread.id)
        self.assertEqual(first_thread.langgraph_thread_id, f"lg-{first_thread.id}")
        self.assertEqual(fresh_thread.langgraph_thread_id, f"lg-{fresh_thread.id}")

    def test_print_thread_history_renders_roles(self) -> None:
        with patch("scripts.terminal_chat.hash_password", return_value="hashed-password"):
            user = terminal_chat.ensure_terminal_user(self.db)
        thread = terminal_chat.ensure_terminal_thread(self.db, user=user)

        self.db.add_all(
            [
                Message(
                    thread_id=thread.id,
                    user_id=user.id,
                    role="user",
                    content="我最近有点累",
                    input_type="text",
                    created_at=utcnow(),
                ),
                Message(
                    thread_id=thread.id,
                    user_id=user.id,
                    role="assistant",
                    content="我在，慢慢说。",
                    input_type="system",
                    created_at=utcnow(),
                ),
            ]
        )
        self.db.commit()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            terminal_chat.print_thread_history(self.db, thread, limit=10)

        output = buffer.getvalue()
        self.assertIn("You: 我最近有点累", output)
        self.assertIn("Assistant: 我在，慢慢说。", output)


if __name__ == "__main__":
    unittest.main()
