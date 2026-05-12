from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.api.v1.endpoints import auth, me, memory
from app.core.security import create_access_token
from app.db.models import (
    Base,
    ConversationThread,
    ConversationTurn,
    Message,
    MoodLog,
    PendingMemoryJob,
    RiskEvent,
    User,
    UserMemory,
    UserProfile,
    UserSettings,
    utcnow,
)
from app.db.session import get_db_session
from app.schemas.chat import SendMessageRequest
from app.services import chat_service
from app.services.memory_job_service import claim_pending_memory_jobs, process_memory_job, process_pending_memory_jobs


class MemoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "0"
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
        self.app.include_router(memory.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        if self.original_vector_retrieval is None:
            os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
        else:
            os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = self.original_vector_retrieval
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo", *, memory_mode: str = "summary_only") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname=username,
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode=memory_mode,
                    companion_style="gentle",
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

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def add_memory(
        self,
        user: User,
        *,
        content: str,
        memory_type: str = "session_summary",
        visibility: str = "user_visible",
    ) -> UserMemory:
        memory_record = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            content=content,
            visibility=visibility,
            status="active",
        )
        self.db.add(memory_record)
        self.db.commit()
        self.db.refresh(memory_record)
        return memory_record

    def test_memory_center_lists_only_active_user_visible_memories(self) -> None:
        user = self.create_user()
        self.add_memory(user, content="可见摘要")
        self.add_memory(user, content="内部安全记录", visibility="internal_safety")
        deleted = self.add_memory(user, content="已删除摘要")
        deleted.status = "deleted"
        self.db.commit()

        response = self.client.get("/api/v1/memories", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["content"] for item in response.json()["items"]], ["可见摘要"])

    def test_memory_mutations_are_scoped_to_owner_and_visible_memories(self) -> None:
        user = self.create_user("owner")
        other = self.create_user("other")
        visible = self.add_memory(user, content="旧内容")
        hidden = self.add_memory(user, content="内部安全记录", visibility="internal_safety")
        other_memory = self.add_memory(other, content="他人的记忆")

        update_response = self.client.patch(
            f"/api/v1/memories/{visible.id}",
            headers=self.auth_headers(user),
            json={"content": "新内容"},
        )
        hidden_response = self.client.patch(
            f"/api/v1/memories/{hidden.id}",
            headers=self.auth_headers(user),
            json={"content": "不应修改"},
        )
        other_response = self.client.delete(f"/api/v1/memories/{other_memory.id}", headers=self.auth_headers(user))

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["content"], "新内容")
        self.assertEqual(hidden_response.status_code, 404)
        self.assertEqual(other_response.status_code, 404)

    def test_memory_document_exports_only_visible_markdown(self) -> None:
        user = self.create_user()
        self.add_memory(user, content="可见摘要", memory_type="session_summary")
        self.add_memory(user, content="内部安全记录", visibility="internal_safety")

        response = self.client.get("/api/v1/memories/document", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers.get("content-type", ""))
        self.assertIn("# 记忆文档", response.text)
        self.assertIn("可见摘要", response.text)
        self.assertNotIn("内部安全记录", response.text)

    def test_clear_memories_soft_deletes_only_visible_memories(self) -> None:
        user = self.create_user()
        visible = self.add_memory(user, content="可见摘要")
        hidden = self.add_memory(user, content="内部安全记录", visibility="internal_safety")

        with patch("app.api.v1.endpoints.memory.remove_memory_vectors", create=True) as remove_vectors:
            response = self.client.delete("/api/v1/memories", headers=self.auth_headers(user))
        self.db.refresh(visible)
        self.db.refresh(hidden)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(visible.status, "deleted")
        self.assertEqual(hidden.status, "active")
        remove_vectors.assert_called_once_with([visible.id])

    def test_search_memories_uses_mode_and_risk_filters(self) -> None:
        user = self.create_user(memory_mode="long_term")
        trigger = self.add_memory(user, content="考试前容易焦虑", memory_type="recurring_trigger")
        self.add_memory(user, content="内部安全摘要", memory_type="safety_summary", visibility="internal_safety")

        normal_response = self.client.post(
            "/api/v1/memories/search",
            headers=self.auth_headers(user),
            json={"query": "我又开始考试焦虑了", "limit": 5},
        )
        high_risk_response = self.client.post(
            "/api/v1/memories/search",
            headers=self.auth_headers(user),
            json={"query": "我不想活了", "risk_level": "L2", "limit": 5},
        )

        self.assertEqual(normal_response.status_code, 200)
        normal_items = normal_response.json()["items"]
        hit = next(item for item in normal_items if item["memory_id"] == trigger.id)
        self.assertGreater(hit["score"], 0)
        self.assertTrue(hit["why_selected"])
        self.db.refresh(trigger)
        self.assertEqual(trigger.access_count, 1)
        self.assertEqual(high_risk_response.status_code, 200)
        self.assertEqual([item["memory_type"] for item in high_risk_response.json()["items"]], ["safety_summary"])
        audit_actions = [
            item["action"]
            for item in self.client.get("/api/v1/memories/audit", headers=self.auth_headers(user)).json()["items"]
        ]
        self.assertIn("retrieve", audit_actions)

    def test_search_and_audit_are_scoped_to_current_user(self) -> None:
        user = self.create_user("owner", memory_mode="long_term")
        other = self.create_user("other", memory_mode="long_term")
        self.add_memory(other, content="exam anxiety belongs to another user", memory_type="recurring_trigger")

        other_response = self.client.post(
            "/api/v1/memories/search",
            headers=self.auth_headers(other),
            json={"query": "exam anxiety", "limit": 5},
        )
        owner_response = self.client.post(
            "/api/v1/memories/search",
            headers=self.auth_headers(user),
            json={"query": "exam anxiety", "limit": 5},
        )
        owner_audit = self.client.get("/api/v1/memories/audit", headers=self.auth_headers(user))

        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(len(other_response.json()["items"]), 1)
        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response.json()["items"], [])
        self.assertEqual(owner_audit.status_code, 200)
        self.assertEqual(owner_audit.json()["items"], [])

    def test_memory_feedback_can_disable_memory_and_audit_it(self) -> None:
        user = self.create_user()
        memory_record = self.add_memory(user, content="用户喜欢先被安抚", memory_type="preference")

        response = self.client.post(
            f"/api/v1/memories/{memory_record.id}/feedback",
            headers=self.auth_headers(user),
            json={"feedback": "dont_use", "note": "这条不准确"},
        )
        audit_response = self.client.get("/api/v1/memories/audit", headers=self.auth_headers(user))
        self.db.refresh(memory_record)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(memory_record.status, "deleted")
        self.assertEqual(memory_record.review_state, "do_not_use")
        self.assertEqual(audit_response.status_code, 200)
        self.assertIn("feedback", [item["action"] for item in audit_response.json()["items"]])

    def test_consolidate_merges_duplicates_and_writes_mood_state(self) -> None:
        user = self.create_user(memory_mode="long_term")
        first = self.add_memory(user, content="用户希望先被安抚", memory_type="preference")
        duplicate = self.add_memory(user, content="用户希望先被安抚", memory_type="preference")
        self.db.add_all(
            [
                MoodLog(user_id=user.id, mood_score=2, mood_tags=["焦虑"], source="checkin"),
                MoodLog(user_id=user.id, mood_score=3, mood_tags=["焦虑", "疲惫"], source="checkin"),
                MoodLog(user_id=user.id, mood_score=2, mood_tags=["疲惫"], source="checkin"),
            ]
        )
        self.db.commit()

        response = self.client.post("/api/v1/memories/consolidate?force=true", headers=self.auth_headers(user))
        self.db.refresh(first)
        self.db.refresh(duplicate)
        memory_types = list(
            self.db.scalars(
                select(UserMemory.memory_type).where(UserMemory.user_id == user.id, UserMemory.status == "active")
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertIn("state", memory_types)
        self.assertEqual([first.status, duplicate.status].count("deleted"), 1)

    def test_update_settings_and_auth_me_return_latest_values(self) -> None:
        user = self.create_user()
        custom_style = "先用两句话接住我的情绪，然后只给一个很小的下一步，不要一下子列太多建议。"

        response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(user),
            json={
                "memory_mode": "long_term",
                "companion_style": custom_style,
                "voice_enabled": True,
                "save_voice_audio": True,
            },
        )
        me_response = self.client.get("/api/v1/auth/me", headers=self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["memory_mode"], "long_term")
        self.assertEqual(response.json()["companion_style"], custom_style)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["memory_mode"], "long_term")
        self.assertEqual(me_response.json()["companion_style"], custom_style)
        self.assertTrue(me_response.json()["voice_enabled"])
        self.assertTrue(me_response.json()["save_voice_audio"])

        restore_response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(user),
            json={"companion_style": ""},
        )

        self.assertEqual(restore_response.status_code, 200)
        self.assertEqual(restore_response.json()["companion_style"], "")

    def test_update_settings_rejects_invalid_memory_mode(self) -> None:
        user = self.create_user()

        response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(user),
            json={"memory_mode": "everything"},
        )

        self.assertEqual(response.status_code, 422)


class FakeGraphRuntime:
    def __init__(self, *, risk_level: str = "L0") -> None:
        self.risk_level = risk_level
        self.calls: list[dict] = []

    async def invoke_turn(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        retrieved_memories = list(kwargs.get("retrieved_memories") or [])
        referenced_memories = []
        if self.risk_level not in {"L2", "L3"}:
            referenced_memories = [
                {
                    "memory_id": memory["id"],
                    "memory_type": memory["memory_type"],
                    "content": memory["content"],
                }
                for memory in retrieved_memories
                if memory.get("visibility") == "user_visible"
            ]

        candidates = [
            {"memory_type": "session_summary", "content": "本轮可见摘要", "importance": 3},
            {"memory_type": "preference", "content": "用户喜欢先被安抚", "importance": 4},
            {"memory_type": "recurring_trigger", "content": "考试前容易焦虑", "importance": 4},
            {"memory_type": "support_strategy", "content": "60 秒呼吸有帮助", "importance": 4},
        ]
        if self.risk_level in {"L2", "L3"}:
            candidates = [{"memory_type": "safety_summary", "content": "本轮安全摘要", "importance": 5}]

        return {
            "assistant_text": "我在。",
            "risk_level": self.risk_level,
            "intent": "other",
            "risk_reasons": [],
            "suggested_actions": ["我还想说"],
            "session_summary": "本轮可见摘要" if self.risk_level == "L0" else "本轮安全摘要",
            "memory_candidates": candidates,
            "should_write_memory": True,
            "referenced_memories": referenced_memories,
        }


class SlowGraphRuntime:
    async def invoke_turn(self, **kwargs) -> dict[str, object]:
        await asyncio.sleep(5)
        return {}


class ChatMemoryModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "0"
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, class_=Session)
        self.db = self.SessionLocal()
        self.original_graph_runtime = chat_service.graph_runtime
        self.original_settings = chat_service.settings

    def tearDown(self) -> None:
        if self.original_vector_retrieval is None:
            os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
        else:
            os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = self.original_vector_retrieval
        chat_service.graph_runtime = self.original_graph_runtime
        chat_service.settings = self.original_settings
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user_with_thread(self, *, memory_mode: str) -> tuple[User, ConversationThread]:
        user = User(username=f"user-{memory_mode}", password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname="demo",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode=memory_mode,
                    companion_style="gentle",
                    voice_enabled=False,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="CN",
                ),
            ]
        )
        thread = ConversationThread(user_id=user.id, langgraph_thread_id=f"lg-{memory_mode}", title="new session")
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(user)
        self.db.refresh(thread)
        return user, thread

    async def test_claim_pending_memory_jobs_uses_row_level_lock(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        turn = ConversationTurn(
            user_id=user.id,
            thread_id=thread.id,
            client_message_id="client-claim-lock",
            request_hash="hash-claim-lock",
            turn_status="completed",
            response_snapshot={},
        )
        self.db.add(turn)
        self.db.flush()
        job = PendingMemoryJob(
            user_id=user.id,
            thread_id=thread.id,
            turn_id=turn.id,
            assistant_message_id=None,
            job_type="memory_write",
            status="pending",
            attempt_count=0,
            max_attempts=3,
            next_run_at=utcnow(),
            payload={"should_write_memory": False},
        )
        self.db.add(job)
        self.db.commit()

        captured_statement = None

        def fake_scalars(statement):
            nonlocal captured_statement
            captured_statement = statement
            return [job]

        with patch.object(self.db, "scalars", side_effect=fake_scalars):
            claimed = claim_pending_memory_jobs(self.db, limit=1, worker_id="worker-a")

        self.assertEqual(claimed, [job])
        self.assertIsNotNone(captured_statement)
        self.assertIn("FOR UPDATE", str(captured_statement.compile(dialect=postgresql.dialect())).upper())
        self.assertIn("SKIP LOCKED", str(captured_statement.compile(dialect=postgresql.dialect())).upper())
        self.db.refresh(job)
        self.assertEqual(job.status, "running")
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.locked_by, "worker-a")

    def add_memory(
        self,
        user: User,
        *,
        memory_type: str,
        content: str,
        importance: int = 3,
        visibility: str = "user_visible",
    ) -> UserMemory:
        memory_record = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            visibility=visibility,
            status="active",
        )
        self.db.add(memory_record)
        self.db.commit()
        self.db.refresh(memory_record)
        return memory_record

    async def test_off_mode_does_not_retrieve_or_write_memories(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="off")
        self.add_memory(user, memory_type="session_summary", content="旧摘要")
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        _, _, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="我最近压力好大"),
        )
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))

        self.assertEqual(fake_runtime.calls[0]["retrieved_memories"], [])
        self.assertEqual(result["referenced_memories"], [])
        self.assertEqual(len(memories), 1)

    async def test_chat_turn_timeout_returns_failed_no_reply_without_assistant_row(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        chat_service.graph_runtime = SlowGraphRuntime()
        chat_service.settings = replace(chat_service.settings, chat_turn_timeout_seconds=0.1)

        _, assistant_message, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="失恋了。"),
        )
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))
        assistant_rows = list(
            self.db.scalars(
                select(Message).where(
                    Message.thread_id == thread.id,
                    Message.role == "assistant",
                )
            )
        )

        self.assertEqual(result["control_reasons"], ["graph_timeout_fallback"])
        self.assertIsNone(assistant_message)
        self.assertEqual(result["delivery_status"], "failed_no_reply")
        self.assertEqual(result["assistant_text"], "")
        self.assertEqual(result["suggested_actions"], [])
        self.assertEqual(result["referenced_memories"], [])
        self.assertFalse(result["should_write_memory"])
        self.assertEqual(assistant_rows, [])
        self.assertEqual(memories, [])

    async def test_high_risk_chat_turn_timeout_persists_safety_fallback(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        chat_service.graph_runtime = SlowGraphRuntime()
        chat_service.settings = replace(chat_service.settings, chat_turn_timeout_seconds=0.1)

        _, assistant_message, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="我现在想自杀，刀在手里"),
        )
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))

        self.assertIsNotNone(assistant_message)
        self.assertEqual(result["delivery_status"], "safety_fallback")
        self.assertEqual(assistant_message.content, result["assistant_text"])
        self.assertIn("安全", assistant_message.content)
        self.assertEqual(result["referenced_memories"], [])
        self.assertFalse(result["retryable"])
        self.assertFalse(result["should_write_memory"])
        self.assertEqual(memories, [])

    async def test_summary_only_mode_retrieves_and_writes_only_session_summaries(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        summary_memory = self.add_memory(user, memory_type="session_summary", content="旧摘要", importance=1)
        self.add_memory(user, memory_type="preference", content="旧偏好", importance=5)
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        _, _, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="我希望你先安抚我"),
        )
        pending_jobs = list(self.db.scalars(select(PendingMemoryJob).where(PendingMemoryJob.thread_id == thread.id)))
        memory_types_before = list(self.db.scalars(select(UserMemory.memory_type).where(UserMemory.user_id == user.id)))
        await process_pending_memory_jobs(self.db)
        memory_types = list(self.db.scalars(select(UserMemory.memory_type).where(UserMemory.user_id == user.id)))

        self.assertEqual([memory["id"] for memory in fake_runtime.calls[0]["retrieved_memories"]], [summary_memory.id])
        self.assertEqual(result["referenced_memories"][0]["memory_id"], summary_memory.id)
        self.assertEqual(result["memory_job_status"], "pending")
        self.assertEqual(len(pending_jobs), 1)
        self.assertEqual(memory_types_before.count("session_summary"), 1)
        self.assertEqual(memory_types.count("session_summary"), 2)
        self.assertEqual(memory_types.count("preference"), 1)

    async def test_long_term_mode_writes_categorized_visible_memories(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="long_term")
        self.add_memory(user, memory_type="preference", content="旧偏好", importance=5)
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="我希望你先听我说，再帮我梳理"),
        )
        await process_pending_memory_jobs(self.db)
        memory_types = set(self.db.scalars(select(UserMemory.memory_type).where(UserMemory.user_id == user.id)))

        self.assertTrue({"session_summary", "preference", "recurring_trigger", "support_strategy"}.issubset(memory_types))
        self.assertGreaterEqual(len(fake_runtime.calls[0]["retrieved_memories"]), 1)

    async def test_long_term_turn_passes_specific_preference_and_metadata(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="long_term")
        preference = self.add_memory(
            user,
            memory_type="preference",
            content="prefers reassurance before problem solving",
            importance=2,
        )
        fake_runtime = FakeGraphRuntime()
        chat_service.graph_runtime = fake_runtime

        _, assistant_message, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="I need reassurance before problem solving"),
        )

        retrieved_ids = [memory["id"] for memory in fake_runtime.calls[0]["retrieved_memories"]]
        self.assertIn(preference.id, retrieved_ids)
        self.assertIn("memory_index", fake_runtime.calls[0])
        self.assertIn(preference.id, [item["memory_id"] for item in fake_runtime.calls[0]["memory_index"]])
        self.assertIn("memory_index", assistant_message.meta)
        self.assertIn("memory_write_decisions", assistant_message.meta)
        self.assertEqual(result["memory_write_decisions"][0]["status"], "pending")
        await process_pending_memory_jobs(self.db)
        self.db.refresh(assistant_message)
        self.assertEqual(assistant_message.meta["memory_job_status"], "completed")
        self.assertEqual(assistant_message.meta["memory_write_decisions"][0]["status"], "created")

    async def test_failed_memory_job_does_not_issue_an_intermediate_commit(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        turn = ConversationTurn(
            user_id=user.id,
            thread_id=thread.id,
            client_message_id="client-memory-job-failure",
            request_hash="hash-memory-job-failure",
            turn_status="completed",
            response_snapshot={},
        )
        assistant_message = Message(
            thread_id=thread.id,
            user_id=user.id,
            role="assistant",
            content="assistant reply",
            meta={},
        )
        self.db.add_all([turn, assistant_message])
        self.db.flush()

        job = PendingMemoryJob(
            user_id=user.id,
            thread_id=thread.id,
            turn_id=turn.id,
            assistant_message_id=assistant_message.id,
            job_type="memory_write",
            status="pending",
            attempt_count=0,
            max_attempts=1,
            next_run_at=utcnow(),
            payload={
                "should_write_memory": True,
                "memory_candidates": [{"memory_type": "session_summary", "content": "keep this"}],
                "session_summary": "keep this",
                "risk_level": "L0",
                "memory_policy": "write_safe_summary",
                "memory_mode": "summary_only",
            },
        )
        self.db.add(job)
        self.db.commit()

        with patch.object(self.db, "commit", wraps=self.db.commit) as commit_spy:
            with patch(
                "app.services.memory_job_service.upsert_memory_candidates",
                side_effect=RuntimeError("boom"),
            ):
                result = await process_memory_job(self.db, job.id)

        self.db.refresh(job)
        self.db.refresh(assistant_message)
        self.db.refresh(turn)

        self.assertIsNotNone(result)
        self.assertEqual(commit_spy.call_count, 1)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNone(job.locked_at)
        self.assertIsNone(job.locked_by)
        self.assertTrue((job.last_error or "").startswith("RuntimeError: boom"))
        self.assertEqual(assistant_message.meta["memory_job_status"], "failed")
        self.assertEqual(turn.response_snapshot["memory_job_status"], "failed")

    async def test_high_risk_turn_does_not_create_visible_memory_but_records_risk_event(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="long_term")
        visible = self.add_memory(user, memory_type="preference", content="prefers reassurance first", importance=5)
        safety = self.add_memory(
            user,
            memory_type="safety_summary",
            content="prior internal safety summary",
            importance=5,
            visibility="internal_safety",
        )
        fake_runtime = FakeGraphRuntime(risk_level="L2")
        chat_service.graph_runtime = fake_runtime

        _, _, result = await chat_service.process_message_turn(
            self.db,
            user=user,
            thread=thread,
            payload=SendMessageRequest(content="我真的不想活了"),
        )
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))
        risk_events = list(self.db.scalars(select(RiskEvent).where(RiskEvent.user_id == user.id)))
        retrieved_ids = [memory["id"] for memory in fake_runtime.calls[0]["retrieved_memories"]]
        indexed_ids = [memory["memory_id"] for memory in fake_runtime.calls[0]["memory_index"]]

        self.assertEqual(result["referenced_memories"], [])
        self.assertEqual(len(risk_events), 1)
        self.assertIn(safety.id, retrieved_ids)
        self.assertNotIn(visible.id, retrieved_ids)
        self.assertEqual(indexed_ids, [safety.id])
        created = [memory for memory in memories if memory.id not in {visible.id, safety.id}]
        self.assertEqual(len(created), 0)
        await process_pending_memory_jobs(self.db)
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))
        created = [memory for memory in memories if memory.id not in {visible.id, safety.id}]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].memory_type, "safety_summary")
        self.assertEqual(created[0].visibility, "internal_safety")


if __name__ == "__main__":
    unittest.main()
