from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ConversationThread, Message, User, UserProfile, UserSettings
from app.schemas.chat import SendMessageRequest
from app.services import chat_service


class ToolingIntegrationTests(unittest.IsolatedAsyncioTestCase):
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

    def create_user(self, *, memory_mode: str = "summary_only", user_mode: str = "adult") -> User:
        user = User(username="tool-user", password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname="Tester",
                    age_range="18_plus",
                    user_mode=user_mode,
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode=memory_mode,
                    companion_style="",
                    voice_enabled=False,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="US",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_thread(self, user: User) -> ConversationThread:
        thread = ConversationThread(
            user_id=user.id,
            langgraph_thread_id=f"lg-{user.id}",
            title="new session",
            mode="companion",
        )
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(thread)
        return thread

    async def test_process_message_turn_carries_tool_audit_and_memory_patch(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        fake_reply = {
            "assistant_text": "I can offer reassurance first, and we can slow this down together.",
            "suggested_actions": ["take one slow breath", "name one thing you can feel"],
            "session_summary": "The user wants reassurance before problem solving.",
            "memory_candidates": [
                {
                    "memory_type": "preference",
                    "title": "Reassurance first",
                    "summary": "User prefers reassurance before planning.",
                    "content": "User prefers reassurance before planning.",
                    "importance": 4,
                    "tags": ["support_style"],
                }
            ],
            "should_write_memory": True,
            "memory_policy": "write_safe_summary",
            "tool_events": [
                {
                    "tool_call_id": "call-1",
                    "name": "search_memories",
                    "arguments": {"query": "reassurance"},
                    "status": "completed",
                    "error": None,
                }
            ],
            "tool_trace_summary": {
                "tool_count": 1,
                "tool_names": ["search_memories"],
                "status_counts": {"completed": 1},
                "error_count": 0,
            },
        }

        with (
            patch("app.graphs.nodes.rag_nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[])),
            patch("app.services.tooling.run_dialogue_reply_with_tools", new=AsyncMock(return_value=fake_reply)),
        ):
            _, assistant_message, result = await chat_service.process_message_turn(
                self.db,
                user=user,
                thread=thread,
                payload=SendMessageRequest(content="I need reassurance before I think about next steps."),
            )

        self.assertIsNotNone(assistant_message)
        self.assertEqual(result["session_summary"], fake_reply["session_summary"])
        self.assertEqual(result["memory_candidates"][0]["memory_type"], "preference")
        self.assertEqual(result["tool_trace_summary"]["tool_count"], 1)
        self.assertEqual(result["tool_events"][0]["name"], "search_memories")
        self.assertEqual(assistant_message.meta["memory_job_status"], "pending")
        self.assertEqual(assistant_message.meta["trace_summary"]["tooling"]["tool_count"], 1)
        self.assertEqual(assistant_message.meta["trace_summary"]["tooling"]["tool_names"], ["search_memories"])

        assistant_rows = list(
            self.db.query(Message)
            .filter(Message.thread_id == thread.id, Message.role == "assistant")
        )
        self.assertEqual(len(assistant_rows), 1)
        self.assertIn("reassurance", assistant_rows[0].content.lower())


if __name__ == "__main__":
    unittest.main()
