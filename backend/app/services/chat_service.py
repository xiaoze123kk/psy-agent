from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import ConversationThread, Message, RiskEvent, User, UserMemory, utcnow
from app.schemas.chat import SendMessageRequest
from app.services.graph_runtime import GraphRuntime


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
    if memory_mode == "off":
        return []

    filters = [
        UserMemory.user_id == user_id,
        UserMemory.status == "active",
        UserMemory.visibility == "user_visible",
    ]
    if memory_mode == "summary_only":
        filters.append(UserMemory.memory_type == "session_summary")

    memories = list(
        db.scalars(
            select(UserMemory)
            .where(*filters)
            .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
            .limit(limit)
        )
    )
    return [
        {
            "id": memory.id,
            "memory_type": memory.memory_type,
            "content": memory.content,
            "visibility": memory.visibility,
            "updated_at": memory.updated_at.isoformat(),
        }
        for memory in memories
    ]


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
    if not bool(assistant_result.get("should_write_memory")):
        return []

    memory_mode = getattr(user.settings, "memory_mode", "summary_only") if user.settings else "summary_only"
    if memory_mode == "off":
        return []

    risk_level = str(assistant_result.get("risk_level", "L0"))
    default_summary = str(assistant_result.get("session_summary") or "").strip()
    candidates = [
        candidate
        for candidate in assistant_result.get("memory_candidates", [])
        if isinstance(candidate, dict) and str(candidate.get("content", "")).strip()
    ]
    if not candidates and default_summary:
        candidates = [
            {
                "memory_type": "session_summary" if risk_level in {"L0", "L1"} else "safety_summary",
                "content": default_summary,
                "importance": 5 if risk_level in {"L2", "L3"} else 3,
            }
        ]
    if not candidates:
        return []

    allowed_types = {"session_summary", "safety_summary"}
    if memory_mode == "long_term":
        allowed_types.update({"preference", "recurring_trigger", "support_strategy"})

    written: list[UserMemory] = []
    for candidate in candidates:
        memory_type = str(candidate.get("memory_type") or "session_summary")
        if memory_type not in allowed_types:
            continue
        if memory_mode == "summary_only" and risk_level in {"L0", "L1"} and memory_type != "session_summary":
            continue

        summary = str(candidate.get("content", "")).strip()
        if not summary:
            continue

        visibility = "internal_safety" if memory_type == "safety_summary" or risk_level in {"L2", "L3"} else "user_visible"
        existing = db.scalar(
            select(UserMemory)
            .where(
                UserMemory.user_id == user.id,
                UserMemory.status == "active",
                UserMemory.visibility == visibility,
                UserMemory.memory_type == memory_type,
                UserMemory.content == summary,
            )
            .order_by(desc(UserMemory.updated_at))
        )
        if existing is not None:
            existing.updated_at = utcnow()
            existing.structured_value = {
                "thread_id": thread.id,
                "risk_level": risk_level,
            }
            written.append(existing)
            continue

        try:
            importance = int(candidate.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        importance = max(1, min(5, importance))

        memory = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            content=summary,
            structured_value={
                "thread_id": thread.id,
                "risk_level": risk_level,
            },
            importance=importance,
            confidence=0.7,
            source_thread_id=thread.id,
            source_message_id=assistant_message.id,
            visibility=visibility,
            status="active",
        )
        db.add(memory)
        db.flush()
        written.append(memory)
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
        retrieved_memories = _list_memory_context_for_user(db, user.id, memory_mode=memory_mode)
        assistant_result = await graph_runtime.invoke_turn(
            thread_id=thread.langgraph_thread_id,
            user_id=user.id,
            content=payload.content,
            input_type=payload.input_type.value,
            user_mode=effective_user_mode,
            recent_messages=[
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
            ],
            last_summary=thread.last_summary,
            memory_mode=memory_mode,
            companion_style=getattr(user.settings, "companion_style", "gentle") if user.settings else "gentle",
            nickname=getattr(user.profile, "nickname", None) if user.profile else None,
            retrieved_memories=retrieved_memories,
        )

        assistant_metadata = {
            "intent": assistant_result.get("intent", "other"),
            "risk_reasons": assistant_result.get("risk_reasons", []),
            "suggested_actions": assistant_result.get("suggested_actions", []),
            "session_summary": assistant_result.get("session_summary", ""),
            "should_write_memory": assistant_result.get("should_write_memory", False),
            "referenced_memories": assistant_result.get("referenced_memories", []),
            "referenced_counseling_examples": assistant_result.get("referenced_counseling_examples", []),
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

        _maybe_write_summary_memory(
            db,
            user=user,
            thread=thread,
            assistant_message=assistant_message,
            assistant_result=assistant_result,
        )

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
