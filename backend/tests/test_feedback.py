from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import feedback
from app.core.security import create_access_token
from app.db.models import Base, ConversationThread, ConversationTurn, Message, User, UserFeedback
from app.db.session import get_db_session


class FeedbackApiTests(unittest.TestCase):
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
        self.app.include_router(feedback.router, prefix="/api/v1")

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

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def test_submit_feedback_assistant_message(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "target_id": "msg-abc-123",
                "rating": 5,
                "tags": ["有帮助", "温暖"],
                "note": "回复很贴心",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "recorded")
        self.assertTrue(body["feedback_id"])

    def test_submit_feedback_knowledge_answer(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "knowledge_answer",
                "target_id": "knowledge-msg-001",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recorded")

    def test_submit_feedback_test_result(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "test_result",
                "target_id": "attempt-xyz-456",
                "rating": 4,
                "tags": ["有趣"],
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_submit_feedback_rejects_invalid_rating_low(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "rating": 0,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_rejects_invalid_rating_high(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "rating": 6,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_rejects_invalid_target_type(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "invalid_type",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_requires_auth(self) -> None:
        response = self.client.post(
            "/api/v1/feedback",
            json={
                "target_type": "assistant_message",
                "rating": 3,
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_submit_feedback_without_note(self) -> None:
        user = self.create_user()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "target_type": "assistant_message",
                "target_id": "msg-test-001",
                "rating": 2,
                "tags": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recorded")

    def test_submit_conversation_quality_feedback_updates_turn_trace_placeholder(self) -> None:
        user = self.create_user()
        thread = ConversationThread(user_id=user.id, langgraph_thread_id="lg-feedback-thread")
        self.db.add(thread)
        self.db.flush()
        assistant = Message(
            user_id=user.id,
            thread_id=thread.id,
            role="assistant",
            content="回复内容",
            meta={
                "trace_summary": {
                    "conversation_quality": {
                        "user_signal": {"explicit_feedback": "none", "next_turn_signal": "unknown"}
                    }
                }
            },
        )
        self.db.add(assistant)
        self.db.flush()
        turn = ConversationTurn(
            user_id=user.id,
            thread_id=thread.id,
            client_message_id="client-feedback-1",
            request_hash="hash-feedback-1",
            turn_status="completed",
            assistant_message_id=assistant.id,
            response_snapshot={
                "conversation_quality_trace": {
                    "user_signal": {"explicit_feedback": "none", "next_turn_signal": "unknown"}
                },
                "trace_summary": {
                    "conversation_quality": {
                        "user_signal": {"explicit_feedback": "none", "next_turn_signal": "unknown"}
                    }
                },
            },
        )
        self.db.add(turn)
        self.db.commit()

        response = self.client.post(
            "/api/v1/feedback",
            headers=self.auth_headers(user),
            json={
                "thread_id": thread.id,
                "turn_id": turn.id,
                "feedback": "too_analytic",
                "optional_note": "这轮太像分析了",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recorded")
        saved_feedback = self.db.query(UserFeedback).one()
        self.assertEqual(saved_feedback.target_type, "conversation_turn")
        self.assertEqual(saved_feedback.target_id, turn.id)
        self.assertEqual(saved_feedback.tags, ["too_analytic"])
        self.assertEqual(saved_feedback.rating, 2)

        self.db.refresh(turn)
        self.db.refresh(assistant)
        quality_trace = turn.response_snapshot["conversation_quality_trace"]
        self.assertEqual(quality_trace["user_signal"]["explicit_feedback"], "too_analytic")
        self.assertEqual(
            assistant.meta["trace_summary"]["conversation_quality"]["user_signal"]["explicit_feedback"],
            "too_analytic",
        )

    def test_conversation_quality_summary_counts_private_trace_fields(self) -> None:
        user = self.create_user()
        thread = ConversationThread(user_id=user.id, langgraph_thread_id="lg-quality-summary")
        self.db.add(thread)
        self.db.flush()
        self.db.add_all(
            [
                ConversationTurn(
                    user_id=user.id,
                    thread_id=thread.id,
                    client_message_id="summary-client-1",
                    request_hash="summary-hash-1",
                    turn_status="completed",
                    response_snapshot={
                        "conversation_quality_trace": {
                            "turn_shape": {"assistant_length_bucket": "short", "question_count": 2},
                            "policy_snapshot": {
                                "conversation_move": "respond_to_anchor",
                                "voice_mode": "anchored_companion",
                            },
                            "validator_snapshot": {
                                "severity": "warning",
                                "validator_reasons": ["generic_buttons"],
                                "experience_reasons": ["violated_voice_contract"],
                            },
                            "user_signal": {
                                "explicit_feedback": "too_many_questions",
                                "next_turn_signal": "corrected",
                            },
                        }
                    },
                ),
                ConversationTurn(
                    user_id=user.id,
                    thread_id=thread.id,
                    client_message_id="summary-client-2",
                    request_hash="summary-hash-2",
                    turn_status="completed",
                    response_snapshot={
                        "trace_summary": {
                            "conversation_quality": {
                                "turn_shape": {"assistant_length_bucket": "short", "question_count": 0},
                                "policy_snapshot": {
                                    "conversation_move": "continue_thread",
                                    "voice_mode": "quiet_presence",
                                },
                                "validator_snapshot": {
                                    "severity": "passed",
                                    "experience_reasons": [],
                                },
                                "user_signal": {
                                    "explicit_feedback": "good",
                                    "next_turn_signal": "continued",
                                },
                            }
                        }
                    },
                ),
            ]
        )
        self.db.commit()

        response = self.client.get(
            f"/api/v1/feedback/conversation-quality/summary?thread_id={thread.id}",
            headers=self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_turns"], 2)
        self.assertEqual(body["feedback_counts"]["too_many_questions"], 1)
        self.assertEqual(body["feedback_counts"]["good"], 1)
        self.assertEqual(body["next_turn_signal_counts"]["corrected"], 1)
        self.assertEqual(body["conversation_move_counts"]["respond_to_anchor"], 1)
        self.assertEqual(body["voice_mode_counts"]["quiet_presence"], 1)
        self.assertEqual(body["validator_reason_counts"]["generic_buttons"], 1)
        self.assertEqual(body["experience_reason_counts"]["violated_voice_contract"], 1)
        self.assertEqual(body["negative_feedback_by_move"]["respond_to_anchor"], 1)
        self.assertNotIn("private", str(body).lower())


if __name__ == "__main__":
    unittest.main()
