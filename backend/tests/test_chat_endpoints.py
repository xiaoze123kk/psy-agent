from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import chat
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, Message, User
from app.db.session import get_db_session


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

    def test_stream_failed_no_reply_emits_null_assistant_message_id(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)

        with patch("app.api.v1.endpoints.chat.process_message_turn", new=AsyncMock(side_effect=self.fake_failed_turn)):
            response = self.client.post(
                f"/api/v1/chat/threads/{thread.id}/stream",
                headers=self.auth_headers(user),
                json={"content": "那条街有太多回忆了"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("event: final", body)
        self.assertIn('"assistant_message_id": null', body)
        self.assertIn('"delivery_status": "failed_no_reply"', body)
        self.assertNotIn("event: token", body)
