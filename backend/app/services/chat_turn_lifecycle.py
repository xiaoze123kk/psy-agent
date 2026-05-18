from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ConversationThread, ConversationTurn, Message, User, generate_uuid, utcnow
from app.schemas.chat import SendMessageRequest
from app.services.conversation_quality_service import infer_next_turn_signal


logger = logging.getLogger("app.services.chat_service")
TURN_RUNNING_WAIT_SECONDS = 1.0
TURN_RUNNING_POLL_INTERVAL_SECONDS = 0.1


@dataclass
class TurnClaim:
    turn: ConversationTurn
    replay: bool


def request_hash(payload: SendMessageRequest) -> str:
    user_mode = payload.user_mode.value if payload.user_mode is not None else None
    body = {
        "content": payload.content,
        "input_type": payload.input_type.value,
        "user_mode": user_mode,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def dict_copy(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def set_quality_next_turn_signal(payload: dict | None, signal: str) -> dict:
    updated = dict_copy(payload)

    quality_trace = dict_copy(updated.get("conversation_quality_trace"))
    quality_user_signal = dict_copy(quality_trace.get("user_signal"))
    quality_user_signal["next_turn_signal"] = signal
    quality_trace["user_signal"] = quality_user_signal
    updated["conversation_quality_trace"] = quality_trace

    trace_summary = dict_copy(updated.get("trace_summary"))
    summary_quality = dict_copy(trace_summary.get("conversation_quality"))
    summary_user_signal = dict_copy(summary_quality.get("user_signal"))
    summary_user_signal["next_turn_signal"] = signal
    summary_quality["user_signal"] = summary_user_signal
    trace_summary["conversation_quality"] = summary_quality
    updated["trace_summary"] = trace_summary

    return updated


def backfill_previous_turn_next_signal(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    current_turn: ConversationTurn,
    current_user_text: str,
) -> None:
    signal = infer_next_turn_signal(current_user_text)
    if signal == "unknown":
        return

    previous_turn = db.scalar(
        select(ConversationTurn)
        .where(
            ConversationTurn.user_id == user.id,
            ConversationTurn.thread_id == thread.id,
            ConversationTurn.id != current_turn.id,
            ConversationTurn.turn_status == "completed",
        )
        .order_by(desc(ConversationTurn.created_at))
        .limit(1)
    )
    if previous_turn is None:
        return

    previous_turn.response_snapshot = set_quality_next_turn_signal(previous_turn.response_snapshot, signal)
    previous_turn.updated_at = utcnow()

    if previous_turn.assistant_message_id:
        assistant_message = db.get(Message, previous_turn.assistant_message_id)
        if assistant_message is not None and assistant_message.user_id == user.id and assistant_message.thread_id == thread.id:
            assistant_message.meta = set_quality_next_turn_signal(assistant_message.meta, signal)


def turn_metadata(turn: ConversationTurn | None) -> dict[str, str]:
    if turn is None:
        return {}
    return {
        "turn_id": turn.id,
        "client_message_id": turn.client_message_id,
    }


def turn_response_fields(turn: ConversationTurn) -> dict[str, object]:
    return {
        "turn_id": turn.id,
        "client_message_id": turn.client_message_id,
        "turn_status": turn.turn_status,
    }


def turn_conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "message": message,
        },
    )


async def wait_for_running_turn(db: Session, turn: ConversationTurn) -> bool:
    deadline = monotonic() + TURN_RUNNING_WAIT_SECONDS
    while monotonic() < deadline:
        await asyncio.sleep(TURN_RUNNING_POLL_INTERVAL_SECONDS)
        db.expire(turn)
        db.refresh(turn)
        if turn.turn_status == "completed":
            return True
        if turn.turn_status == "failed":
            return False
    db.expire(turn)
    db.refresh(turn)
    return turn.turn_status == "completed"


async def claim_turn(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
    wait_for_running: bool,
) -> TurnClaim:
    client_message_id = payload.client_message_id or generate_uuid()
    request_hash_value = request_hash(payload)
    existing = db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.user_id == user.id,
            ConversationTurn.thread_id == thread.id,
            ConversationTurn.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash_value:
            raise turn_conflict(
                "idempotency_key_conflict",
                "client_message_id already exists for a different message payload.",
            )
        if existing.turn_status == "completed":
            return TurnClaim(turn=existing, replay=True)
        if existing.turn_status == "running":
            if wait_for_running and await wait_for_running_turn(db, existing):
                return TurnClaim(turn=existing, replay=True)
            raise turn_conflict("turn_running", "Conversation turn is still running.")
        if existing.turn_status == "failed":
            raise turn_conflict("turn_failed", "Conversation turn failed before it produced a replayable result.")
        raise turn_conflict("turn_unavailable", "Conversation turn is not replayable yet.")

    turn = ConversationTurn(
        user_id=user.id,
        thread_id=thread.id,
        client_message_id=client_message_id,
        request_hash=request_hash_value,
        turn_status="running",
    )
    db.add(turn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return await claim_turn(
            db,
            user=user,
            thread=thread,
            payload=payload,
            wait_for_running=wait_for_running,
        )
    db.refresh(turn)
    return TurnClaim(turn=turn, replay=False)


def complete_turn(
    turn: ConversationTurn,
    *,
    user_message: Message,
    assistant_message: Message | None,
    assistant_result: dict[str, object],
) -> dict[str, object]:
    turn.turn_status = "completed"
    turn.delivery_status = str(assistant_result.get("delivery_status", "generated"))
    failure_reason = assistant_result.get("failure_reason")
    turn.failure_reason = str(failure_reason) if failure_reason is not None else None
    turn.retryable = bool(assistant_result.get("retryable", False))
    turn.user_message_id = user_message.id
    turn.assistant_message_id = assistant_message.id if assistant_message is not None else None
    turn.updated_at = utcnow()
    result = {
        **assistant_result,
        **turn_response_fields(turn),
    }
    turn.response_snapshot = json_safe(result)
    return result


def mark_turn_failed(db: Session, turn_id: str | None, reason: str) -> None:
    if turn_id is None:
        return
    try:
        turn = db.get(ConversationTurn, turn_id)
        if turn is None or turn.turn_status == "completed":
            return
        turn.turn_status = "failed"
        turn.delivery_status = "failed_no_reply"
        turn.failure_reason = reason
        turn.retryable = True
        turn.updated_at = utcnow()
        turn.response_snapshot = json_safe(
            {
                "assistant_text": "",
                "delivery_status": "failed_no_reply",
                "failure_reason": reason,
                "retryable": True,
                **turn_response_fields(turn),
            }
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to mark conversation turn as failed.")


def replay_turn_result(db: Session, turn: ConversationTurn) -> tuple[Message, Message | None, dict[str, object]]:
    if not turn.user_message_id:
        raise turn_conflict("turn_result_unavailable", "Conversation turn has no user message to replay.")
    user_message = db.get(Message, turn.user_message_id)
    if user_message is None:
        raise turn_conflict("turn_result_unavailable", "Conversation turn user message is missing.")
    assistant_message = db.get(Message, turn.assistant_message_id) if turn.assistant_message_id else None
    snapshot = dict(turn.response_snapshot or {})
    if not snapshot:
        raise turn_conflict("turn_result_unavailable", "Conversation turn has no response snapshot to replay.")
    snapshot.update(turn_response_fields(turn))
    return user_message, assistant_message, snapshot
