from __future__ import annotations

import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import chat
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, ConversationTurn, Message, User
from app.db.session import get_db_session
from app.services import chat_service


class FakeGraphRuntime:
    def __init__(self, *, assistant_text: str = "我在。") -> None:
        self.assistant_text = assistant_text
        self.calls: list[dict] = []

    def _result(self) -> dict[str, object]:
        return {
            "assistant_text": self.assistant_text,
            "risk_level": "L0",
            "intent": "other",
            "risk_reasons": [],
            "suggested_actions": ["继续说"],
            "session_summary": "本轮摘要",
            "memory_candidates": [],
            "should_write_memory": False,
            "referenced_memories": [],
            "referenced_counseling_examples": [],
        }

    async def invoke_turn(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        return self._result()

    async def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        yield "graph_result", self._result()


class ChatIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "0"
        self.original_graph_runtime = chat_service.graph_runtime
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
        chat_service.graph_runtime = self.original_graph_runtime
        if self.original_vector_retrieval is None:
            os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
        else:
            os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = self.original_vector_retrieval
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

    def message_count(self, thread: ConversationThread) -> int:
        return int(self.db.scalar(select(func.count()).select_from(Message).where(Message.thread_id == thread.id)) or 0)

    def turn_count(self, thread: ConversationThread) -> int:
        return int(
            self.db.scalar(select(func.count()).select_from(ConversationTurn).where(ConversationTurn.thread_id == thread.id))
            or 0
        )

    def test_same_client_message_id_replays_completed_turn(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime
        payload = {"client_message_id": "client-1", "content": "我今天压力很大"}

        first = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)
        second = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["message_id"], second.json()["message_id"])
        self.assertEqual(first.json()["assistant_message_id"], second.json()["assistant_message_id"])
        self.assertEqual(first.json()["turn_id"], second.json()["turn_id"])
        self.assertEqual(first.json()["client_message_id"], "client-1")
        self.assertEqual(self.message_count(thread), 2)
        self.assertEqual(self.turn_count(thread), 1)
        self.assertEqual(len(fake_runtime.calls), 1)

    def test_same_client_message_id_with_different_content_conflicts(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        chat_service.graph_runtime = FakeGraphRuntime()

        first = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-1", "content": "我今天压力很大"},
        )
        conflict = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-1", "content": "这是另一条消息"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "idempotency_key_conflict")
        self.assertEqual(self.message_count(thread), 2)
        self.assertEqual(self.turn_count(thread), 1)

    def test_failed_no_reply_turn_is_replayed_without_assistant_message(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        fake_runtime = FakeGraphRuntime(assistant_text="")
        chat_service.graph_runtime = fake_runtime
        payload = {"client_message_id": "client-failed", "content": "我说不出来"}

        first = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)
        second = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["delivery_status"], "failed_no_reply")
        self.assertIsNone(first.json()["assistant_message_id"])
        self.assertEqual(first.json()["message_id"], second.json()["message_id"])
        self.assertEqual(self.message_count(thread), 1)
        self.assertEqual(self.turn_count(thread), 1)
        self.assertEqual(len(fake_runtime.calls), 1)

    def test_legacy_request_without_client_message_id_still_succeeds(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        chat_service.graph_runtime = FakeGraphRuntime()

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"content": "没有客户端幂等键"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["client_message_id"])
        self.assertTrue(body["turn_id"])
        self.assertEqual(body["turn_status"], "completed")
        self.assertEqual(self.message_count(thread), 2)
        self.assertEqual(self.turn_count(thread), 1)

    def test_stream_completed_turn_can_be_replayed_by_send_message_fallback(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime
        payload = {"client_message_id": "client-stream", "content": "先走流式"}

        stream_response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/stream",
            headers=self.auth_headers(user),
            json=payload,
        )
        fallback_response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json=payload,
        )

        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("event: final", stream_response.text)
        self.assertEqual(fallback_response.status_code, 200)
        self.assertEqual(self.message_count(thread), 2)
        self.assertEqual(self.turn_count(thread), 1)
        self.assertEqual(len(fake_runtime.calls), 1)
