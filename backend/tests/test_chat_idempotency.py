from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import chat
from app.core.security import create_access_token
from app.db.models import (
    Base,
    ConversationThread,
    ConversationTurn,
    ConversationTurnTrace,
    Message,
    PendingMemoryJob,
    User,
    UserMemory,
    UserProfile,
    UserSettings,
)
from app.db.session import get_db_session
from app.services import chat_service
from app.services.graph_runtime import GraphRuntime


class FakeGraphRuntime:
    def __init__(
        self,
        *,
        assistant_text: str = "我在。",
        should_write_memory: bool = False,
        memory_candidates: list[dict[str, object]] | None = None,
    ) -> None:
        self.assistant_text = assistant_text
        self.should_write_memory = should_write_memory
        self.memory_candidates = memory_candidates or []
        self.calls: list[dict] = []

    def _result(self) -> dict[str, object]:
        started_at = datetime.now(timezone.utc)
        return {
            "assistant_text": self.assistant_text,
            "risk_level": "L0",
            "intent": "other",
            "risk_reasons": [],
            "suggested_actions": ["继续说"],
            "session_summary": "本轮摘要",
            "session_digest": {
                "key_themes": ["职场压力"],
                "emotional_arc": "紧绷 -> 稍微稳定",
                "summary_200chars": "用户本轮继续讨论职场压力。",
            },
            "memory_candidates": self.memory_candidates,
            "should_write_memory": self.should_write_memory,
            "referenced_memories": [],
            "referenced_counseling_examples": [],
            "rag_used": True,
            "rag_skipped_reason": "",
            "graph_trace": [
                {
                    "sequence": 0,
                    "trace_type": "graph_node",
                    "node_name": "risk_classifier",
                    "status": "completed",
                    "started_at": started_at,
                    "completed_at": started_at + timedelta(milliseconds=4),
                    "duration_ms": 4,
                    "output_summary": {
                        "risk_level": "L0",
                        "risk_reason_codes": [],
                        "user_text": "private user text",
                    },
                    "reason_codes": [],
                    "error_code": None,
                },
                {
                    "sequence": 1,
                    "trace_type": "graph_node",
                    "node_name": "response_validator",
                    "status": "completed",
                    "started_at": started_at + timedelta(milliseconds=4),
                    "completed_at": started_at + timedelta(milliseconds=9),
                    "duration_ms": 5,
                    "output_summary": {
                        "delivery_status": "generated" if self.assistant_text else "failed_no_reply",
                        "validator_blocked": False,
                        "retrieved_counseling_examples": [{"content": "private rag passage"}],
                        "assistant_text": "private assistant text",
                    },
                    "reason_codes": [],
                    "error_code": None,
                },
            ],
        }

    async def invoke_turn(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        return self._result()

    async def stream_turn(self, **kwargs):
        self.calls.append(kwargs)
        if self.assistant_text:
            yield "token", {"text": self.assistant_text}
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

    def trace_count(self, thread: ConversationThread) -> int:
        return int(
            self.db.scalar(
                select(func.count()).select_from(ConversationTurnTrace).where(ConversationTurnTrace.thread_id == thread.id)
            )
            or 0
        )

    def memory_job_count(self, thread: ConversationThread) -> int:
        return int(
            self.db.scalar(select(func.count()).select_from(PendingMemoryJob).where(PendingMemoryJob.thread_id == thread.id))
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
        self.assertEqual(self.trace_count(thread), 2)
        self.assertEqual(len(fake_runtime.calls), 1)

    def test_replay_does_not_create_duplicate_memory_job(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        fake_runtime = FakeGraphRuntime(
            should_write_memory=True,
            memory_candidates=[{"memory_type": "session_summary", "content": "memory summary"}],
        )
        chat_service.graph_runtime = fake_runtime
        payload = {"client_message_id": "client-memory-job", "content": "remember this"}

        first = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)
        second = self.client.post(f"/api/v1/chat/threads/{thread.id}/messages", headers=self.auth_headers(user), json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["assistant_message"]["memory_job_status"], "pending")
        self.assertEqual(second.json()["assistant_message"]["memory_job_status"], "pending")
        self.assertEqual(first.json()["assistant_message"]["trace_summary"]["memory"]["job_status"], "pending")
        self.assertEqual(self.memory_job_count(thread), 1)
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
        self.assertEqual(self.trace_count(thread), 2)
        self.assertEqual(self.memory_job_count(thread), 0)
        turn = self.db.scalar(select(ConversationTurn).where(ConversationTurn.thread_id == thread.id))
        self.assertIn("trace_summary", turn.response_snapshot)
        self.assertEqual(turn.response_snapshot["trace_summary"]["delivery_status"], "failed_no_reply")
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

    def test_session_digest_persists_without_replacing_last_summary(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        chat_service.graph_runtime = FakeGraphRuntime()

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-digest", "content": "我最近工作压力很大"},
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(thread)
        self.assertEqual(thread.last_summary, "本轮摘要")
        self.assertEqual(thread.session_digest["key_themes"], ["职场压力"])
        self.assertEqual(thread.session_digest["summary_200chars"], "用户本轮继续讨论职场压力。")

    def test_chat_turn_passes_user_profile_digest_to_graph_runtime(self) -> None:
        user = self.create_user("profiled")
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname="小林",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=["先安抚再建议"],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode="long_term",
                    companion_style="先短短安抚我，再给一个小步骤",
                    voice_enabled=False,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="CN",
                ),
                UserMemory(
                    user_id=user.id,
                    memory_type="preference",
                    title="preference: 不要一上来就连环追问",
                    summary="用户不喜欢一上来就连环追问",
                    content="用户不喜欢一上来就连环追问",
                    visibility="user_visible",
                    status="active",
                    review_state="normal",
                ),
            ]
        )
        self.db.commit()
        thread = self.create_thread(user)
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-profile-digest", "content": "我今天有点乱"},
        )

        self.assertEqual(response.status_code, 200)
        digest = fake_runtime.calls[0]["user_profile_digest"]
        self.assertEqual(digest["nickname"], "小林")
        self.assertEqual(digest["age_range"], "18_plus")
        self.assertIn("先安抚再建议", digest["usage_goals"])
        self.assertTrue(any("先短短安抚我" in item for item in digest["communication_preferences"]))
        self.assertIn("用户不喜欢一上来就连环追问", digest["preference_hints"])

    def test_graph_runtime_input_state_includes_user_context_pack(self) -> None:
        runtime = object.__new__(GraphRuntime)
        pack = {
            "schema_version": 1,
            "active_goal": "理清楚主管沟通任务边界",
            "style_corrections": ["不要直接给模板"],
        }

        state = runtime._build_input_state(
            thread_id="thread-1",
            user_id="user-1",
            content="继续",
            user_context_pack=pack,
        )

        self.assertEqual(state["user_context_pack"], pack)

    def test_recent_message_candidates_include_larger_context_window(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        base_time = datetime.now(timezone.utc) - timedelta(minutes=40)
        for index in range(30):
            self.db.add(
                Message(
                    thread_id=thread.id,
                    user_id=user.id,
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"历史消息 {index}",
                    input_type="text",
                    created_at=base_time + timedelta(seconds=index),
                )
            )
        self.db.commit()
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-wide-context", "content": "接着前面的任务边界聊"},
        )

        self.assertEqual(response.status_code, 200)
        recent_messages = fake_runtime.calls[0]["recent_messages"]
        self.assertEqual(len(recent_messages), 24)
        self.assertEqual(recent_messages[0]["content"], "历史消息 7")
        self.assertEqual(recent_messages[-1]["content"], "接着前面的任务边界聊")

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
        self.assertEqual(stream_response.text.count("event: token"), 1)
        self.assertEqual(fallback_response.status_code, 200)
        self.assertEqual(self.message_count(thread), 2)
        self.assertEqual(self.turn_count(thread), 1)
        self.assertEqual(self.trace_count(thread), 2)
        self.assertEqual(len(fake_runtime.calls), 1)

    def test_trace_rows_are_sanitized_and_trace_summary_is_saved(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        chat_service.graph_runtime = FakeGraphRuntime()

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/messages",
            headers=self.auth_headers(user),
            json={"client_message_id": "client-trace", "content": "private original content"},
        )

        self.assertEqual(response.status_code, 200)
        traces = list(
            self.db.scalars(
                select(ConversationTurnTrace)
                .where(ConversationTurnTrace.thread_id == thread.id)
                .order_by(ConversationTurnTrace.sequence)
            )
        )
        self.assertEqual([trace.sequence for trace in traces], [0, 1])
        trace_payload = str([(trace.output_summary, trace.reason_codes) for trace in traces])
        self.assertNotIn("private user text", trace_payload)
        self.assertNotIn("private original content", trace_payload)
        self.assertNotIn("private rag passage", trace_payload)
        self.assertNotIn("private assistant text", trace_payload)
        self.assertIn("risk_level", trace_payload)
        self.assertIn("delivery_status", trace_payload)

        assistant_message = self.db.get(Message, response.json()["assistant_message_id"])
        turn = self.db.scalar(select(ConversationTurn).where(ConversationTurn.thread_id == thread.id))
        response_trace = response.json()["assistant_message"]["trace_summary"]
        self.assertEqual(response_trace["node_count"], 2)
        self.assertEqual(response_trace["mode"]["risk_level"], "L0")
        self.assertEqual(response_trace["memory"]["retrieved_count"], 0)
        self.assertTrue(response_trace["rag"]["used"])
        self.assertFalse(response_trace["validator"]["blocked"])
        self.assertEqual(response_trace["steps"][1]["node_name"], "response_validator")
        self.assertEqual(assistant_message.meta["trace_summary"]["node_count"], 2)
        self.assertEqual(turn.response_snapshot["trace_summary"]["node_count"], 2)
