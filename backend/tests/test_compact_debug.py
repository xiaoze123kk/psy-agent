from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import compact_debug
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, Message, User
from app.db.session import get_db_session
from app.services.compact_debug_service import (
    build_compact_debug_view,
    build_manual_compact_preview,
)


def _msg(index: int, role: str, content: str, **metadata):
    return {
        "id": f"msg-{index}",
        "role": role,
        "content": content,
        "metadata": metadata,
        "risk_level": metadata.get("risk_level"),
        "created_at": f"2026-05-17T12:{index:02d}:00+08:00",
    }


class CompactDebugServiceTests(unittest.TestCase):
    def test_debug_view_uses_latest_assistant_compact_pack_without_raw_json_prompt(self) -> None:
        pack = {
            "schema_version": 1,
            "source": "runtime_compact_context",
            "event": {
                "type": "compact_event",
                "trigger": {"reason": ["quality_repetition_risk"]},
                "range": {"forgotten_turn_ids": ["turn-1", "turn-2"]},
            },
            "state": {
                "summary_for_prompt": "用户现在主要在表达生气。",
                "stale_threads": [{"topic": "在轮下", "reuse_policy": "不要主动复用"}],
                "quality_signals": {"recent_repetition_risk": "high"},
            },
            "memory_candidates": [],
        }
        messages = [
            _msg(1, "user", "早前的话题"),
            _msg(2, "assistant", "回应", compact_context_pack=pack),
        ]

        view = build_compact_debug_view(
            recent_messages=messages,
            session_digest={},
            risk_level="L0",
        )

        self.assertTrue(view["has_compact"])
        self.assertEqual(view["latest_event"]["trigger"]["reason"], ["quality_repetition_risk"])
        self.assertEqual(view["state"]["summary_for_prompt"], "用户现在主要在表达生气。")
        self.assertIn("用户现在主要在表达生气", view["prompt_view"])
        self.assertIn("在轮下", view["prompt_view"])
        self.assertNotIn("compact_context_pack", view["prompt_view"])
        self.assertNotIn("schema_version", view["prompt_view"])
        self.assertEqual(view["metrics"]["memory_candidate_count"], 0)

    def test_manual_preview_applies_hint_and_does_not_persist_or_expose_raw_keys(self) -> None:
        messages = [
            _msg(1, "user", "我刚才说在轮下那个感觉。"),
            _msg(2, "assistant", "我听到了这个锚点。"),
            _msg(3, "user", "以后不要连续追问我，我更希望你先听我说完。"),
        ]

        preview = build_manual_compact_preview(
            recent_messages=messages,
            session_digest={"summary_200chars": "用户早前提到在轮下，后来转向互动边界。"},
            risk_level="L0",
            focus=["保留用户明确边界", "丢弃 stale 旧锚点"],
            created_at="2026-05-17T12:40:00+08:00",
        )

        self.assertFalse(preview["persisted"])
        self.assertIn("manual_hint", preview["pack"]["event"]["trigger"]["reason"])
        self.assertEqual(preview["pack"]["event"]["hint"]["focus"], ["保留用户明确边界", "丢弃 stale 旧锚点"])
        self.assertIn("保留用户明确边界", preview["prompt_diff"]["with_compact"])
        self.assertIn("丢弃 stale 旧锚点", preview["prompt_diff"]["with_compact"])
        self.assertIn("当前会话压缩状态", preview["prompt_diff"]["with_compact"])
        self.assertNotIn("compact_context_pack", preview["prompt_diff"]["with_compact"])
        self.assertNotIn("schema_version", preview["prompt_diff"]["with_compact"])


class CompactDebugEndpointTests(unittest.TestCase):
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
        self.app.include_router(compact_debug.router, prefix="/api/v1")

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
            title="compact debug",
            mode="companion",
            session_digest={"summary_200chars": "用户在整理互动边界。"},
        )
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(thread)
        return thread

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def add_message(self, thread: ConversationThread, user: User, role: str, content: str, **metadata) -> None:
        self.db.add(
            Message(
                thread_id=thread.id,
                user_id=user.id,
                role=role,
                content=content,
                input_type="text",
                meta=metadata,
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()

    def test_get_compact_debug_returns_latest_view(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        pack = {
            "schema_version": 1,
            "event": {"type": "compact_event", "trigger": {"reason": ["message_threshold"]}},
            "state": {"summary_for_prompt": "用户在整理互动边界。"},
            "memory_candidates": [],
        }
        self.add_message(thread, user, "assistant", "回应", compact_context_pack=pack)

        response = self.client.get(
            f"/api/v1/chat/threads/{thread.id}/compact/debug",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["has_compact"])
        self.assertEqual(body["latest_event"]["trigger"]["reason"], ["message_threshold"])
        self.assertIn("用户在整理互动边界", body["prompt_view"])

    def test_manual_compact_preview_is_not_persisted(self) -> None:
        user = self.create_user()
        thread = self.create_thread(user)
        self.add_message(thread, user, "user", "以后不要连续追问我。")

        response = self.client.post(
            f"/api/v1/chat/threads/{thread.id}/compact/preview",
            headers=self.auth_headers(user),
            json={"focus": ["保留互动边界"], "max_recent_messages": 6},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["persisted"])
        self.assertIn("manual_hint", body["pack"]["event"]["trigger"]["reason"])
        self.assertIn("保留互动边界", body["prompt_diff"]["with_compact"])
