from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import ConversationThread, Message, RiskEvent, User, UserMemory, utcnow
from app.graphs.nodes import sync_risk_classify
from app.schemas.chat import SendMessageRequest
from app.services.graph_runtime import GraphRuntime
from app.services.memory_service import (
    build_memory_index,
    index_memory_embeddings,
    maybe_auto_consolidate_user_memories,
    retrieve_memories_for_turn,
    upsert_memory_candidates,
)


graph_runtime = GraphRuntime()


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
) -> tuple[Message, Message, dict[str, object]]:
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
        retrieved_memories = retrieve_memories_for_turn(
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
        assistant_result = await graph_runtime.invoke_turn(
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
        )

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

        if not thread.title or thread.title == "new session":
            thread.title = payload.content[:20] if payload.content else "new session"
        thread.last_summary = str(assistant_result.get("session_summary", "") or "")
        thread.last_risk_level = str(assistant_result.get("risk_level", "L0"))
        thread.updated_at = utcnow()

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
