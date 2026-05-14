from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import chat
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, Message, User
from app.db.session import get_db_session
from app.schemas.chat import SendMessageRequest


class ChatEndpointTests(unittest.TestCase):
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
        self.app.include_router(chat.router, prefix="/api/v1")

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

    def create_thread(self, user: User) -> ConversationThread:
        thread = ConversationThread(
            user_id=user.id,
            langgraph_thread_id=f"lg-{user.username}",
            title="new session",
            mode="companion",
        )
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(thread)
        return thread

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def fake_failed_turn(self, db: Session, **kwargs):
        user_message = Message(
            thread_id=kwargs["thread"].id,
            user_id=kwargs["user"].id,
            role="user",
            content=kwargs["payload"].content,
            input_type=kwargs["payload"].input_type.value,
            meta={},
        )
        db.add(user_message)
        db.flush()
        return user_message, None, {
            "assistant_text": "",
            "risk_level": "L1",
            "delivery_status": "failed_no_reply",
            "failure_reason": "graph_timeout_fallback",
            "retryable": True,
            "suggested_actions": [],
            "referenced_memories": [],
            "referenced_counseling_examples": [],
            "session_summary": "",
            "should_write_memory": False,
        }

    async def fake_success_stream(self, db: Session, **kwargs):
        yield "accepted", {"thread_id": kwargs["thread"].id, "status": "accepted"}
        yield "graph_update", {"node": "risk_classifier", "status": "completed", "risk_level": "L0"}
        yield "token", {"text": "我在。"}
        yield "final", {
            "thread_id": kwargs["thread"].id,
            "message_id": "user-message-1",
            "assistant_message_id": "assistant-message-1",
            "assistant_text": "我在。",
            "risk_level": "L0",
            "intent": "vent",
            "suggested_actions": ["我想继续说"],
            "session_summary": "用户表达压力。",
            "should_write_memory": False,
            "referenced_memories": [],
            "delivery_status": "generated",
            "failure_reason": None,
            "retryable": False,
        }

    async def fake_failed_stream(self, db: Session, **kwargs):
        yield "accepted", {"thread_id": kwargs["thread"].id, "status": "accepted"}
        yield "graph_update", {"node": "risk_classifier", "status": "completed", "risk_level": "L1"}
        yield "final", {
            "thread_id": kwargs["thread"].id,
            "message_id": "user-message-1",
            "assistant_message_id": None,
            "assistant_text": "",
            "risk_level": "L1",
            "intent": "vent",
            "suggested_actions": [],
            "session_summary": "",
            "should_write_memory": False,
            "referenced_memories": [],
            "delivery_status": "failed_no_reply",
            "failure_reason": "graph_timeout_fallback",
            "retryable": True,
        }

    def test_send_message_failed_no_reply_returns_null_assistant_message(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        with patch("app.api.v1.endpoints.chat.process_message_turn", new=AsyncMock(side_effect=self.fake_failed_turn)):
            response = self.client.post(
                f"/api/v1/chat/threads/{thread.id}/messages",
                headers=self.auth_headers(user),
                json={"content": "那条街有太多回忆了"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["thread_id"], thread.id)
        self.assertIsNotNone(body["message_id"])
        self.assertIsNone(body["assistant_message_id"])
        self.assertIsNone(body["assistant_message"])
        self.assertEqual(body["delivery_status"], "failed_no_reply")
        self.assertTrue(body["retryable"])
        self.assertEqual(body["failure_reason"], "graph_timeout_fallback")

        assistant_count = self.db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.thread_id == thread.id,
                Message.role == "assistant",
            )
        )
        self.assertEqual(assistant_count, 0)

    def test_stream_emits_safe_realtime_sequence(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        with patch("app.api.v1.endpoints.chat.process_message_turn_stream", new=self.fake_success_stream):
            response = self.client.post(
                f"/api/v1/chat/threads/{thread.id}/stream",
                headers=self.auth_headers(user),
                json={"content": "我今天有点累"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.text
        accepted_pos = body.index("event: accepted")
        graph_pos = body.index("event: graph_update")
        token_pos = body.index("event: token")
        final_pos = body.index("event: final")
        self.assertLess(accepted_pos, graph_pos)
        self.assertLess(graph_pos, token_pos)
        self.assertLess(token_pos, final_pos)
        self.assertIn('"node": "risk_classifier"', body)
        self.assertIn('"assistant_text": "我在。"', body)

    def test_stream_message_returns_response_before_turn_finishes(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        async def slow_stream(db: Session, **kwargs):
            yield "accepted", {"thread_id": kwargs["thread"].id, "status": "accepted"}
            await asyncio.sleep(10)

        async def call_endpoint():
            return await chat.stream_message(
                thread.id,
                SendMessageRequest(content="我今天有点累"),
                user,
                self.db,
            )

        with patch("app.api.v1.endpoints.chat.process_message_turn_stream", new=slow_stream):
            response = asyncio.run(asyncio.wait_for(call_endpoint(), timeout=0.2))

        self.assertIsInstance(response, StreamingResponse)

    def test_stream_failed_no_reply_emits_null_assistant_message_id(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        with patch("app.api.v1.endpoints.chat.process_message_turn_stream", new=self.fake_failed_stream):
            response = self.client.post(
                f"/api/v1/chat/threads/{thread.id}/stream",
                headers=self.auth_headers(user),
                json={"content": "那条街有太多回忆了"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("event: accepted", body)
        self.assertIn("event: graph_update", body)
        self.assertIn("event: final", body)
        self.assertIn('"assistant_message_id": null', body)
        self.assertIn('"delivery_status": "failed_no_reply"', body)
        self.assertNotIn("event: token", body)
