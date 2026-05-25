from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    CompanionStyle,
    ConversationThread,
    Message,
    MoodLog,
    PrivacyActionLog,
    RefreshToken,
    RiskEvent,
    TestAttempt,
    TestHistory,
    User,
    UserFeedback,
    UserMemory,
    utcnow,
)
from app.schemas.privacy import PrivacyDataCounts, PrivacyMutationResponse, PrivacySettingsSnapshot, PrivacySummaryResponse
from app.services.companion_style import normalize_custom_companion_style
from app.services.memory_service import remove_memory_vectors


def _count(db: Session, statement) -> int:
    value = db.scalar(statement)
    return int(value or 0)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _thread_ids_for_user(db: Session, user_id: str, *, include_archived: bool = False) -> list[str]:
    filters = [ConversationThread.user_id == user_id]
    if not include_archived:
        filters.append(ConversationThread.archived_at.is_(None))
    return list(db.scalars(select(ConversationThread.id).where(*filters)))


def _active_visible_memory_count(db: Session, user_id: str) -> int:
    return _count(
        db,
        select(func.count(UserMemory.id)).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.visibility == "user_visible",
        ),
    )


def build_privacy_summary(db: Session, user: User) -> PrivacySummaryResponse:
    active_thread_ids = _thread_ids_for_user(db, user.id)
    latest_values = [
        db.scalar(select(func.max(ConversationThread.updated_at)).where(ConversationThread.user_id == user.id)),
        db.scalar(select(func.max(Message.created_at)).where(Message.user_id == user.id)),
        db.scalar(select(func.max(UserMemory.updated_at)).where(UserMemory.user_id == user.id)),
        db.scalar(select(func.max(MoodLog.created_at)).where(MoodLog.user_id == user.id)),
        db.scalar(select(func.max(TestHistory.completed_at)).where(TestHistory.user_id == user.id)),
        db.scalar(select(func.max(UserFeedback.created_at)).where(UserFeedback.user_id == user.id)),
        db.scalar(select(func.max(RiskEvent.created_at)).where(RiskEvent.user_id == user.id)),
    ]
    latest_activity_at = max((value for value in latest_values if value is not None), default=None)

    settings = user.settings
    profile = user.profile
    return PrivacySummaryResponse(
        user_id=user.id,
        user_mode=profile.user_mode if profile else "adult",
        settings=PrivacySettingsSnapshot(
            memory_mode=settings.memory_mode if settings else "summary_only",
        ),
        data_counts=PrivacyDataCounts(
            memories=_active_visible_memory_count(db, user.id),
            chat_threads=len(active_thread_ids),
            chat_messages=_count(
                db,
                select(func.count(Message.id)).where(Message.thread_id.in_(active_thread_ids))
                if active_thread_ids
                else select(func.count(Message.id)).where(False),
            ),
            mood_logs=_count(db, select(func.count(MoodLog.id)).where(MoodLog.user_id == user.id)),
            test_history=_count(db, select(func.count(TestHistory.id)).where(TestHistory.user_id == user.id)),
            feedback=_count(db, select(func.count(UserFeedback.id)).where(UserFeedback.user_id == user.id)),
            risk_events=_count(db, select(func.count(RiskEvent.id)).where(RiskEvent.user_id == user.id)),
        ),
        latest_activity_at=latest_activity_at,
    )


def build_user_data_export(db: Session, user: User) -> dict[str, Any]:
    profile = user.profile
    settings = user.settings
    companion_styles = list(
        db.scalars(
            select(CompanionStyle)
            .where(CompanionStyle.user_id == user.id)
            .order_by(CompanionStyle.sort_order.asc(), CompanionStyle.updated_at.desc())
        )
    )
    active_threads = list(
        db.scalars(
            select(ConversationThread)
            .where(ConversationThread.user_id == user.id, ConversationThread.archived_at.is_(None))
            .order_by(ConversationThread.updated_at.desc())
        )
    )
    thread_ids = [thread.id for thread in active_threads]
    messages_by_thread: dict[str, list[Message]] = {thread_id: [] for thread_id in thread_ids}
    if thread_ids:
        messages = list(
            db.scalars(
                select(Message)
                .where(Message.thread_id.in_(thread_ids))
                .order_by(Message.created_at.asc())
            )
        )
        for message in messages:
            messages_by_thread.setdefault(message.thread_id, []).append(message)

    memories = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user.id,
                UserMemory.status == "active",
                UserMemory.visibility == "user_visible",
            )
            .order_by(UserMemory.updated_at.desc())
        )
    )
    mood_logs = list(db.scalars(select(MoodLog).where(MoodLog.user_id == user.id).order_by(MoodLog.created_at.desc())))
    test_history = list(
        db.scalars(select(TestHistory).where(TestHistory.user_id == user.id).order_by(TestHistory.completed_at.desc()))
    )
    feedback = list(
        db.scalars(select(UserFeedback).where(UserFeedback.user_id == user.id).order_by(UserFeedback.created_at.desc()))
    )
    risk_summary = list(
        db.execute(
            select(RiskEvent.risk_level, func.count(RiskEvent.id))
            .where(RiskEvent.user_id == user.id)
            .group_by(RiskEvent.risk_level)
        )
    )

    return {
        "exported_at": _dt(utcnow()),
        "account": {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "status": user.status,
            "created_at": _dt(user.created_at),
        },
        "profile": {
            "nickname": profile.nickname if profile else None,
            "age_range": profile.age_range if profile else None,
            "user_mode": profile.user_mode if profile else "adult",
            "usage_goals": list(profile.usage_goals or []) if profile else [],
            "onboarding_completed": bool(profile.onboarding_completed) if profile else False,
        },
        "settings": {
            "memory_mode": settings.memory_mode if settings else "summary_only",
            "companion_style": normalize_custom_companion_style(settings.companion_style) if settings else "",
            "crisis_resource_region": settings.crisis_resource_region if settings else "CN",
        },
        "companion_styles": [
            {
                "style_id": style.id,
                "title": style.title,
                "definition": normalize_custom_companion_style(style.definition),
                "is_default": bool(style.is_default),
                "created_at": _dt(style.created_at),
                "updated_at": _dt(style.updated_at),
            }
            for style in companion_styles
        ],
        "memories": [
            {
                "memory_id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title,
                "summary": memory.summary,
                "content": memory.content,
                "tags": list(memory.tags or []),
                "importance": memory.importance,
                "confidence": float(memory.confidence or 0),
                "source": memory.source,
                "review_state": memory.review_state,
                "access_count": memory.access_count,
                "created_at": _dt(memory.created_at),
                "updated_at": _dt(memory.updated_at),
            }
            for memory in memories
        ],
        "chat_threads": [
            {
                "thread_id": thread.id,
                "title": thread.title,
                "mode": thread.mode,
                "last_summary": thread.last_summary,
                "session_digest": thread.session_digest,
                "last_risk_level": thread.last_risk_level,
                "created_at": _dt(thread.created_at),
                "updated_at": _dt(thread.updated_at),
                "messages": [
                    {
                        "message_id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "input_type": message.input_type,
                        "risk_level": message.risk_level,
                        "metadata": message.meta,
                        "created_at": _dt(message.created_at),
                    }
                    for message in messages_by_thread.get(thread.id, [])
                ],
            }
            for thread in active_threads
        ],
        "mood_logs": [
            {
                "log_id": log.id,
                "mood_score": log.mood_score,
                "anxiety_score": log.anxiety_score,
                "energy_score": log.energy_score,
                "sleep_quality": log.sleep_quality,
                "mood_tags": list(log.mood_tags or []),
                "note": log.note,
                "source": log.source,
                "created_at": _dt(log.created_at),
            }
            for log in mood_logs
        ],
        "test_history": [
            {
                "attempt_id": item.attempt_id,
                "test_id": item.test_id,
                "test_title": item.test_title,
                "result_code": item.result_code,
                "result_label": item.result_label,
                "completed_at": _dt(item.completed_at),
            }
            for item in test_history
        ],
        "feedback": [
            {
                "feedback_id": item.id,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "rating": item.rating,
                "tags": list(item.tags or []),
                "note": item.note,
                "created_at": _dt(item.created_at),
            }
            for item in feedback
        ],
        "risk_events_summary": {
            level: count
            for level, count in risk_summary
        },
    }


def _log_privacy_action(db: Session, *, user_id: str, action: str, scope: str, affected_counts: dict[str, int]) -> None:
    db.add(
        PrivacyActionLog(
            user_id=user_id,
            action=action,
            scope=scope,
            affected_counts=dict(affected_counts),
        )
    )


def _delete_memories(db: Session, user_id: str) -> int:
    memory_ids = list(
        db.scalars(select(UserMemory.id).where(UserMemory.user_id == user_id, UserMemory.status == "active"))
    )
    rows = db.execute(
        update(UserMemory)
        .where(UserMemory.id.in_(memory_ids))
        .values(status="deleted", updated_at=utcnow())
    )
    remove_memory_vectors(memory_ids)
    return int(rows.rowcount or 0)


def _delete_chat(db: Session, user_id: str) -> dict[str, int]:
    thread_ids = _thread_ids_for_user(db, user_id)
    if not thread_ids:
        return {"chat_threads": 0, "chat_messages": 0, "chat_memories": 0}

    memory_ids = list(
        db.scalars(
            select(UserMemory.id).where(
                UserMemory.user_id == user_id,
                UserMemory.visibility == "user_visible",
                UserMemory.status == "active",
                UserMemory.source_thread_id.in_(thread_ids),
            )
        )
    )
    db.execute(update(RiskEvent).where(RiskEvent.user_id == user_id).values(message_id=None))
    message_rows = db.execute(delete(Message).where(Message.thread_id.in_(thread_ids)))
    thread_rows = db.execute(
        update(ConversationThread)
        .where(ConversationThread.id.in_(thread_ids), ConversationThread.user_id == user_id)
        .values(archived_at=utcnow(), last_summary=None, session_digest={}, updated_at=utcnow())
    )
    memory_rows = db.execute(
        update(UserMemory)
        .where(UserMemory.id.in_(memory_ids))
        .values(status="deleted", updated_at=utcnow())
    )
    remove_memory_vectors(memory_ids)
    return {
        "chat_threads": int(thread_rows.rowcount or 0),
        "chat_messages": int(message_rows.rowcount or 0),
        "chat_memories": int(memory_rows.rowcount or 0),
    }


def _delete_moods(db: Session, user_id: str) -> int:
    rows = db.execute(delete(MoodLog).where(MoodLog.user_id == user_id))
    return int(rows.rowcount or 0)


def _delete_feedback(db: Session, user_id: str) -> int:
    rows = db.execute(delete(UserFeedback).where(UserFeedback.user_id == user_id))
    return int(rows.rowcount or 0)


def _delete_tests(db: Session, user_id: str) -> dict[str, int]:
    history_rows = db.execute(delete(TestHistory).where(TestHistory.user_id == user_id))
    attempt_rows = db.execute(delete(TestAttempt).where(TestAttempt.user_id == user_id))
    return {
        "test_history": int(history_rows.rowcount or 0),
        "test_attempts": int(attempt_rows.rowcount or 0),
    }


def delete_user_data(db: Session, user: User, *, scope: str) -> PrivacyMutationResponse:
    affected: dict[str, int] = {}
    if scope == "memories":
        affected["memories"] = _delete_memories(db, user.id)
    elif scope == "chat":
        affected.update(_delete_chat(db, user.id))
    elif scope == "moods":
        affected["mood_logs"] = _delete_moods(db, user.id)
    elif scope == "feedback":
        affected["feedback"] = _delete_feedback(db, user.id)
    elif scope == "all_non_account":
        affected["memories"] = _delete_memories(db, user.id)
        affected.update(_delete_chat(db, user.id))
        affected["mood_logs"] = _delete_moods(db, user.id)
        affected["feedback"] = _delete_feedback(db, user.id)
        affected.update(_delete_tests(db, user.id))
    else:
        raise ValueError(f"Unsupported privacy data scope: {scope}")

    _log_privacy_action(db, user_id=user.id, action="delete_data", scope=scope, affected_counts=affected)
    db.commit()
    return PrivacyMutationResponse(status="deleted", scope=scope, affected_counts=affected)


def delete_account(db: Session, user: User) -> PrivacyMutationResponse:
    affected = dict(delete_user_data(db, user, scope="all_non_account").affected_counts)
    token_rows = db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.status == "active")
        .values(status="revoked", revoked_at=utcnow(), last_used_at=utcnow())
    )
    affected["refresh_tokens"] = int(token_rows.rowcount or 0)

    if user.profile is not None:
        user.profile.nickname = "已注销用户"
        user.profile.usage_goals = []
        user.profile.onboarding_completed = False
        user.profile.updated_at = utcnow()
    if user.settings is not None:
        user.settings.memory_mode = "off"
        user.settings.companion_style = ""
        user.settings.updated_at = utcnow()

    style_rows = db.execute(delete(CompanionStyle).where(CompanionStyle.user_id == user.id))
    affected["companion_styles"] = int(style_rows.rowcount or 0)

    user.username = f"deleted_{user.id.replace('-', '')[:20]}"
    user.email = None
    user.phone = None
    user.password_hash = "deleted"
    user.status = "deleted"
    user.deleted_at = utcnow()
    user.updated_at = utcnow()

    _log_privacy_action(db, user_id=user.id, action="delete_account", scope="account", affected_counts=affected)
    db.commit()
    return PrivacyMutationResponse(status="account_deleted", scope="account", affected_counts=affected)
