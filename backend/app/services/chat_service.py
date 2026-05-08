from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ConversationThread, Message, RiskEvent, User, UserMemory, utcnow
from app.graphs.nodes import sync_risk_classify
from app.schemas.chat import SendMessageRequest
from app.services.graph_runtime import GraphRuntime
from app.services.memory_service import (
    build_memory_index,
    index_memory_embeddings,
    maybe_auto_consolidate_user_memories,
    retrieve_memories_for_turn,
    retrieve_memories_for_turn_async,
    upsert_memory_candidates,
)


logger = logging.getLogger(__name__)
graph_runtime = GraphRuntime()


def _failed_no_reply_result(*, risk_level: str, reason: str) -> dict[str, object]:
    return {
        "assistant_text": "",
        "risk_level": risk_level,
        "intent": "vent" if risk_level == "L1" else "other",
        "risk_reasons": [],
        "route_priority": "P2_support",
        "control_category": "fallback",
        "control_reasons": [reason],
        "control_confidence": 0.0,
        "risk_formulation": {"labels": [reason], "observed_reasons": [], "uncertainty": 1.0},
        "response_contract": {},
        "memory_policy": "skip_sensitive",
        "memory_policy_reason": reason,
        "rag_used": False,
        "rag_skipped_reason": reason,
        "example_ids": [],
        "example_source_keys": [],
        "validator_blocked": False,
        "validator_reasons": [],
        "suggested_actions": [],
        "session_summary": "",
        "memory_candidates": [],
        "should_write_memory": False,
        "memory_write_decisions": [{"status": "skipped", "reason": reason}],
        "referenced_memories": [],
        "referenced_counseling_examples": [],
        "delivery_status": "failed_no_reply",
        "failure_reason": reason,
        "retryable": True,
        "audit_tags": [reason],
    }


def _safety_fallback_result(*, risk_level: str, reason: str) -> dict[str, object]:
    assistant_text = (
        "我更关心你现在的安全。先别一个人扛，尽量去有人在的地方，联系可信的人；"
        "如果马上有危险，请立刻拨打当地紧急电话。"
    )
    suggested_actions = ["我现在不安全", "我能联系谁", "先陪我稳住"]

    return {
        "assistant_text": assistant_text,
        "risk_level": risk_level,
        "intent": "crisis",
        "risk_reasons": [],
        "route_priority": "P0_immediate_safety",
        "control_category": "fallback",
        "control_reasons": [reason],
        "control_confidence": 0.0,
        "risk_formulation": {"labels": [reason], "observed_reasons": [], "uncertainty": 1.0},
        "response_contract": {},
        "memory_policy": "crisis_audit_only",
        "memory_policy_reason": reason,
        "rag_used": False,
        "rag_skipped_reason": reason,
        "example_ids": [],
        "example_source_keys": [],
        "validator_blocked": False,
        "validator_reasons": [],
        "suggested_actions": suggested_actions,
        "session_summary": "",
        "memory_candidates": [],
        "should_write_memory": False,
        "memory_write_decisions": [{"status": "skipped", "reason": reason}],
        "referenced_memories": [],
        "referenced_counseling_examples": [],
        "delivery_status": "safety_fallback",
        "failure_reason": reason,
        "retryable": False,
        "audit_tags": [reason],
    }


def _fallback_assistant_result(*, risk_level: str, reason: str) -> dict[str, object]:
    if risk_level in {"L2", "L3"}:
        return _safety_fallback_result(risk_level=risk_level, reason=reason)
    return _failed_no_reply_result(risk_level=risk_level, reason=reason)


def _coerce_delivery_result(result: dict[str, object], *, pre_risk_level: str) -> dict[str, object]:
    delivery_status = str(result.get("delivery_status") or "")
    risk_level = str(result.get("risk_level") or pre_risk_level or "L0")
    assistant_text = str(result.get("assistant_text") or "").strip()

    if not delivery_status:
        delivery_status = "generated" if assistant_text else "failed_no_reply"

    if delivery_status == "generated" and not assistant_text:
        delivery_status = "failed_no_reply"

    if delivery_status == "failed_no_reply" and risk_level in {"L2", "L3"}:
        return _safety_fallback_result(
            risk_level=risk_level,
            reason=str(result.get("failure_reason") or "safety_fallback"),
        )

    if delivery_status == "failed_no_reply":
        result.update(
            {
                "assistant_text": "",
                "suggested_actions": [],
                "session_summary": "",
                "memory_candidates": [],
                "should_write_memory": False,
                "referenced_memories": [],
                "referenced_counseling_examples": [],
                "memory_policy": "skip_sensitive",
                "memory_policy_reason": str(result.get("failure_reason") or "failed_no_reply"),
                "delivery_status": "failed_no_reply",
                "failure_reason": str(result.get("failure_reason") or "failed_no_reply"),
                "retryable": True,
            }
        )
        return result

    result["delivery_status"] = "safety_fallback" if delivery_status == "safety_fallback" else "generated"
    result["failure_reason"] = result.get("failure_reason")
    result["retryable"] = bool(result.get("retryable", False))
    if result["delivery_status"] == "safety_fallback":
        result["referenced_memories"] = []
        result["referenced_counseling_examples"] = []
        result["retryable"] = False
    return result


async def _invoke_graph_with_fallback(
    *,
    thread: ConversationThread,
    user: User,
    payload: SendMessageRequest,
    effective_user_mode: str,
    serialized_recent_messages: list[dict],
    memory_mode: str,
    memory_index: list[dict],
    retrieved_memories: list[dict],
    pre_risk_level: str,
) -> dict[str, object]:
    timeout_seconds = max(float(settings.chat_turn_timeout_seconds), 0.1)
    try:
        return await asyncio.wait_for(
            graph_runtime.invoke_turn(
                thread_id=thread.langgraph_thread_id,
                user_id=user.id,
                content=payload.content,
                input_type=payload.input_type.value,
                user_mode=effective_user_mode,
                recent_messages=serialized_recent_messages,
                last_summary=thread.last_summary,
                memory_mode=memory_mode,
                companion_style=getattr(user.settings, "companion_style", "gentle") if user.settings else "gentle",
                nickname=getattr(user.profile, "nickname", None) if user.profile else None,
                retrieved_memories=retrieved_memories,
                memory_index=memory_index,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning("Chat graph timed out after %.1fs; returning delivery fallback.", timeout_seconds)
        return _fallback_assistant_result(
            risk_level=pre_risk_level,
            reason="graph_timeout_fallback",
        )
    except Exception:
        logger.exception("Chat graph failed; returning delivery fallback.")
        return _fallback_assistant_result(
            risk_level=pre_risk_level,
            reason="graph_error_fallback",
        )


def get_thread_for_user(db: Session, user_id: str, thread_id: str) -> ConversationThread:
    thread = db.scalar(
        select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == user_id,
            ConversationThread.archived_at.is_(None),
        )
    )
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )
    return thread


def list_threads_for_user(db: Session, user_id: str) -> list[ConversationThread]:
    return list(
        db.scalars(
            select(ConversationThread)
            .where(
                ConversationThread.user_id == user_id,
                ConversationThread.archived_at.is_(None),
            )
            .order_by(desc(ConversationThread.updated_at))
        )
    )


def list_messages_for_thread(db: Session, thread_id: str) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at.asc())
        )
    )


def _list_memory_context_for_user(
    db: Session,
    user_id: str,
    *,
    memory_mode: str,
    limit: int = 4,
) -> list[dict]:
    return retrieve_memories_for_turn(
        db,
        user_id=user_id,
        query="",
        memory_mode=memory_mode,
        limit=limit,
        record_access=True,
    )


def _upsert_risk_event(
    db: Session,
    *,
    user_id: str,
    thread_id: str,
    message_id: str | None,
    risk_level: str,
    trigger_text: str,
    action_taken: list[str],
) -> RiskEvent:
    existing = None
    if message_id:
        existing = db.scalar(
            select(RiskEvent).where(
                RiskEvent.user_id == user_id,
                RiskEvent.thread_id == thread_id,
                RiskEvent.message_id == message_id,
            )
        )
    if existing is not None:
        return existing

    event = RiskEvent(
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        risk_level=risk_level,
        trigger_text=trigger_text,
        safety_action_taken=action_taken,
    )
    db.add(event)
    db.flush()
    return event


def _maybe_write_summary_memory(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    assistant_message: Message,
    assistant_result: dict[str, object],
) -> list[UserMemory]:
    written, _ = upsert_memory_candidates(
        db,
        user=user,
        thread=thread,
        assistant_message_id=assistant_message.id,
        assistant_result=assistant_result,
    )
    return written


async def process_message_turn(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
) -> tuple[Message, Message | None, dict[str, object]]:
    try:
        user_message = Message(
            thread_id=thread.id,
            user_id=user.id,
            role="user",
            content=payload.content,
            input_type=payload.input_type.value,
            meta={},
        )
        db.add(user_message)
        db.flush()

        profile_user_mode = getattr(user.profile, "user_mode", "adult") if user.profile else "adult"
        effective_user_mode = payload.user_mode.value if payload.user_mode is not None else profile_user_mode
        recent_messages = list_messages_for_thread(db, thread.id)[-8:]
        memory_mode = getattr(user.settings, "memory_mode", "summary_only") if user.settings else "summary_only"
        serialized_recent_messages = [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "input_type": message.input_type,
                "risk_level": message.risk_level,
                "metadata": message.meta or {},
                "created_at": message.created_at.isoformat(),
            }
            for message in recent_messages
        ]
        pre_risk_level = sync_risk_classify(payload.content)
        memory_index = build_memory_index(
            db,
            user.id,
            memory_mode=memory_mode,
            include_internal=pre_risk_level in {"L2", "L3"},
        )
        retrieved_memories = await retrieve_memories_for_turn_async(
            db,
            user_id=user.id,
            query=payload.content,
            recent_messages=serialized_recent_messages,
            last_summary=thread.last_summary,
            memory_mode=memory_mode,
            risk_level=pre_risk_level,
            limit=5,
            record_access=True,
        )
        assistant_result = await _invoke_graph_with_fallback(
            thread=thread,
            user=user,
            payload=payload,
            effective_user_mode=effective_user_mode,
            serialized_recent_messages=serialized_recent_messages,
            memory_mode=memory_mode,
            memory_index=memory_index,
            retrieved_memories=retrieved_memories,
            pre_risk_level=pre_risk_level,
        )
        assistant_result = _coerce_delivery_result(assistant_result, pre_risk_level=pre_risk_level)
        delivery_status = str(assistant_result.get("delivery_status", "generated"))

        if not thread.title or thread.title == "new session":
            thread.title = payload.content[:20] if payload.content else "new session"
        thread.updated_at = utcnow()
        thread.last_risk_level = str(assistant_result.get("risk_level", pre_risk_level))

        if delivery_status == "failed_no_reply":
            db.commit()
            db.refresh(user_message)
            db.refresh(thread)
            return user_message, None, assistant_result

        assistant_metadata = {
            "intent": assistant_result.get("intent", "other"),
            "risk_reasons": assistant_result.get("risk_reasons", []),
            "suggested_actions": assistant_result.get("suggested_actions", []),
            "session_summary": assistant_result.get("session_summary", ""),
            "should_write_memory": assistant_result.get("should_write_memory", False),
            "referenced_memories": assistant_result.get("referenced_memories", []),
            "referenced_counseling_examples": assistant_result.get("referenced_counseling_examples", []),
            "memory_index": memory_index,
            "memory_write_decisions": [],
            "memory_policy_reason": assistant_result.get("memory_policy", ""),
            "delivery_status": delivery_status,
            "failure_reason": assistant_result.get("failure_reason"),
            "retryable": bool(assistant_result.get("retryable", False)),
        }
        assistant_message = Message(
            thread_id=thread.id,
            user_id=user.id,
            role="assistant",
            content=str(assistant_result.get("assistant_text", "")),
            input_type="system",
            risk_level=str(assistant_result.get("risk_level", "L0")),
            meta=assistant_metadata,
        )
        db.add(assistant_message)
        db.flush()

        thread.last_summary = str(assistant_result.get("session_summary", "") or "")

        risk_level = str(assistant_result.get("risk_level", "L0"))
        if risk_level in {"L2", "L3"}:
            _upsert_risk_event(
                db,
                user_id=user.id,
                thread_id=thread.id,
                message_id=user_message.id,
                risk_level=risk_level,
                trigger_text=payload.content,
                action_taken=list(assistant_result.get("suggested_actions", [])),
            )

        written_memories, memory_write_decisions = upsert_memory_candidates(
            db,
            user=user,
            thread=thread,
            assistant_message_id=assistant_message.id,
            assistant_result=assistant_result,
        )
        assistant_result["memory_write_decisions"] = memory_write_decisions
        assistant_message.meta = {
            **assistant_metadata,
            "memory_write_decisions": memory_write_decisions,
        }
        await index_memory_embeddings(db, written_memories)
        maybe_auto_consolidate_user_memories(db, user_id=user.id)

        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        db.refresh(thread)
        return user_message, assistant_message, assistant_result
    except Exception:
        db.rollback()
        raise


def create_or_get_risk_event(
    db: Session,
    *,
    user_id: str,
    thread_id: str,
    message_id: str | None,
    risk_level: str,
    trigger_text: str,
    action_taken: list[str],
) -> RiskEvent:
    event = _upsert_risk_event(
        db,
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        risk_level=risk_level,
        trigger_text=trigger_text,
        action_taken=action_taken,
    )
    db.commit()
    db.refresh(event)
    return event
