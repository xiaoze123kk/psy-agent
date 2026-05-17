from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import ConversationThread, ConversationTurn, Message, User, UserFeedback, utcnow
from app.db.session import get_db_session
from app.schemas.feedback import FeedbackCreateRequest, FeedbackResponse
from app.services.conversation_quality_service import build_conversation_quality_summary

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _copy_dict(value: object) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def _set_quality_explicit_feedback(payload: dict | None, feedback: str) -> dict:
    updated = _copy_dict(payload)

    quality_trace = _copy_dict(updated.get("conversation_quality_trace"))
    quality_user_signal = _copy_dict(quality_trace.get("user_signal"))
    quality_user_signal["explicit_feedback"] = feedback
    quality_trace["user_signal"] = quality_user_signal
    updated["conversation_quality_trace"] = quality_trace

    trace_summary = _copy_dict(updated.get("trace_summary"))
    summary_quality = _copy_dict(trace_summary.get("conversation_quality"))
    summary_user_signal = _copy_dict(summary_quality.get("user_signal"))
    summary_user_signal["explicit_feedback"] = feedback
    summary_quality["user_signal"] = summary_user_signal
    trace_summary["conversation_quality"] = summary_quality
    updated["trace_summary"] = trace_summary

    return updated


def _conversation_quality_rating(feedback: str) -> int:
    return 5 if feedback == "good" else 2


def _submit_conversation_quality_feedback(
    *,
    payload: FeedbackCreateRequest,
    current_user: User,
    db: Session,
) -> FeedbackResponse:
    turn = db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.id == payload.turn_id,
            ConversationTurn.user_id == current_user.id,
        )
    )
    if turn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation turn not found.")
    if turn.thread_id != payload.thread_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="thread_id does not match turn_id.")

    feedback_value = str(payload.feedback)
    feedback = UserFeedback(
        user_id=current_user.id,
        target_type="conversation_turn",
        target_id=turn.id,
        rating=_conversation_quality_rating(feedback_value),
        tags=[feedback_value],
        note=payload.optional_note,
    )
    db.add(feedback)

    turn.response_snapshot = _set_quality_explicit_feedback(turn.response_snapshot, feedback_value)
    turn.updated_at = utcnow()

    if turn.assistant_message_id:
        assistant_message = db.get(Message, turn.assistant_message_id)
        if (
            assistant_message is not None
            and assistant_message.user_id == current_user.id
            and assistant_message.thread_id == turn.thread_id
        ):
            assistant_message.meta = _set_quality_explicit_feedback(assistant_message.meta, feedback_value)

    db.commit()
    db.refresh(feedback)
    return FeedbackResponse(feedback_id=feedback.id)


@router.get("/conversation-quality/summary")
async def read_conversation_quality_summary(
    thread_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    if thread_id:
        thread = db.scalar(
            select(ConversationThread).where(
                ConversationThread.id == thread_id,
                ConversationThread.user_id == current_user.id,
                ConversationThread.archived_at.is_(None),
            )
        )
        if thread is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")
    return build_conversation_quality_summary(
        db,
        user_id=current_user.id,
        thread_id=thread_id,
        limit=limit,
    )


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> FeedbackResponse:
    if payload.feedback is not None:
        return _submit_conversation_quality_feedback(payload=payload, current_user=current_user, db=db)

    feedback = UserFeedback(
        user_id=current_user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        rating=payload.rating,
        tags=list(payload.tags),
        note=payload.note,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return FeedbackResponse(feedback_id=feedback.id)
