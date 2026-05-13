from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ConversationThread, ConversationTurn, Message, RiskEvent, User, generate_uuid, utcnow
from app.graphs.nodes import sync_risk_classify
from app.schemas.chat import SendMessageRequest
from app.services.graph_runtime import GraphRuntime
from app.services.graph_trace_service import build_delivery_trace, build_trace_summary, persist_turn_traces
from app.services.memory_job_service import build_memory_job_payload, enqueue_memory_job, notify_memory_jobs
from app.services.memory_service import (
    build_memory_index,
    retrieve_memories_for_turn,
    retrieve_memories_for_turn_async,
)


logger = logging.getLogger(__name__)
graph_runtime = GraphRuntime()
ChatStreamEvent = tuple[str, dict[str, object]]
TURN_RUNNING_WAIT_SECONDS = 1.0
TURN_RUNNING_POLL_INTERVAL_SECONDS = 0.1
RECENT_MESSAGE_CANDIDATE_LIMIT = 24


@dataclass
class TurnContext:
    turn: ConversationTurn
    user_message: Message
    effective_user_mode: str
    serialized_recent_messages: list[dict]
    memory_mode: str
    memory_index: list[dict]
    retrieved_memories: list[dict]
    pre_risk_level: str


@dataclass
class TurnClaim:
    turn: ConversationTurn
    replay: bool


def _failed_no_reply_result(*, risk_level: str, reason: str) -> dict[str, object]:
    return {
        "assistant_text": "",
        "risk_level": risk_level,
        "intent": "vent" if risk_level == "L1" else "other",
        "risk_reasons": [],
        "semantic_risk": {},
        "risk_source": "fallback",
        "risk_reason_codes": [],
        "requires_safety_check": False,
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
        "semantic_risk": {},
        "risk_source": "fallback",
        "risk_reason_codes": [],
        "requires_safety_check": True,
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
                session_digest=thread.session_digest or {},
                memory_mode=memory_mode,
                companion_style=getattr(user.settings, "companion_style", "") if user.settings else "",
                nickname=getattr(user.profile, "nickname", None) if user.profile else None,
                crisis_resource_region=getattr(user.settings, "crisis_resource_region", "CN") if user.settings else "CN",
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


def _request_hash(payload: SendMessageRequest) -> str:
    user_mode = payload.user_mode.value if payload.user_mode is not None else None
    body = {
        "content": payload.content,
        "input_type": payload.input_type.value,
        "user_mode": user_mode,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _pop_graph_trace(assistant_result: dict[str, object]) -> list[dict[str, object]]:
    raw_trace = assistant_result.pop("graph_trace", [])
    graph_trace = [record for record in raw_trace if isinstance(record, dict)] if isinstance(raw_trace, list) else []
    if not graph_trace:
        graph_trace = build_delivery_trace(assistant_result)
    assistant_result["trace_summary"] = build_trace_summary(graph_trace, assistant_result)
    return graph_trace


def _turn_metadata(turn: ConversationTurn | None) -> dict[str, str]:
    if turn is None:
        return {}
    return {
        "turn_id": turn.id,
        "client_message_id": turn.client_message_id,
    }


def _turn_response_fields(turn: ConversationTurn) -> dict[str, object]:
    return {
        "turn_id": turn.id,
        "client_message_id": turn.client_message_id,
        "turn_status": turn.turn_status,
    }


def _turn_conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "message": message,
        },
    )


async def _wait_for_running_turn(db: Session, turn: ConversationTurn) -> bool:
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


async def _claim_turn(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
    wait_for_running: bool,
) -> TurnClaim:
    client_message_id = payload.client_message_id or generate_uuid()
    request_hash = _request_hash(payload)
    existing = db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.user_id == user.id,
            ConversationTurn.thread_id == thread.id,
            ConversationTurn.client_message_id == client_message_id,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _turn_conflict(
                "idempotency_key_conflict",
                "client_message_id already exists for a different message payload.",
            )
        if existing.turn_status == "completed":
            return TurnClaim(turn=existing, replay=True)
        if existing.turn_status == "running":
            if wait_for_running and await _wait_for_running_turn(db, existing):
                return TurnClaim(turn=existing, replay=True)
            raise _turn_conflict("turn_running", "Conversation turn is still running.")
        if existing.turn_status == "failed":
            raise _turn_conflict("turn_failed", "Conversation turn failed before it produced a replayable result.")
        raise _turn_conflict("turn_unavailable", "Conversation turn is not replayable yet.")

    turn = ConversationTurn(
        user_id=user.id,
        thread_id=thread.id,
        client_message_id=client_message_id,
        request_hash=request_hash,
        turn_status="running",
    )
    db.add(turn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return await _claim_turn(
            db,
            user=user,
            thread=thread,
            payload=payload,
            wait_for_running=wait_for_running,
        )
    db.refresh(turn)
    return TurnClaim(turn=turn, replay=False)


def _complete_turn(
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
        **_turn_response_fields(turn),
    }
    turn.response_snapshot = _json_safe(result)
    return result


def _mark_turn_failed(db: Session, turn_id: str | None, reason: str) -> None:
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
        turn.response_snapshot = _json_safe(
            {
                "assistant_text": "",
                "delivery_status": "failed_no_reply",
                "failure_reason": reason,
                "retryable": True,
                **_turn_response_fields(turn),
            }
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to mark conversation turn as failed.")


def _replay_turn_result(db: Session, turn: ConversationTurn) -> tuple[Message, Message | None, dict[str, object]]:
    if not turn.user_message_id:
        raise _turn_conflict("turn_result_unavailable", "Conversation turn has no user message to replay.")
    user_message = db.get(Message, turn.user_message_id)
    if user_message is None:
        raise _turn_conflict("turn_result_unavailable", "Conversation turn user message is missing.")
    assistant_message = db.get(Message, turn.assistant_message_id) if turn.assistant_message_id else None
    snapshot = dict(turn.response_snapshot or {})
    if not snapshot:
        raise _turn_conflict("turn_result_unavailable", "Conversation turn has no response snapshot to replay.")
    snapshot.update(_turn_response_fields(turn))
    return user_message, assistant_message, snapshot


def _iter_stream_chunks(text: str, *, chunk_size: int = 6):
    buffer = ""
    stop_chars = set("。！？!?；;\n")
    for char in text:
        buffer += char
        if len(buffer) >= chunk_size or char in stop_chars:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer


def _create_user_message(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
    turn: ConversationTurn,
) -> Message:
    user_message = Message(
        thread_id=thread.id,
        user_id=user.id,
        role="user",
        content=payload.content,
        input_type=payload.input_type.value,
        meta=_turn_metadata(turn),
    )
    db.add(user_message)
    db.flush()
    turn.user_message_id = user_message.id
    return user_message


def _serialize_recent_messages(messages: list[Message]) -> list[dict]:
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "input_type": message.input_type,
            "risk_level": message.risk_level,
            "metadata": message.meta or {},
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]


async def _prepare_turn_context(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
    user_message: Message,
    turn: ConversationTurn,
) -> TurnContext:
    profile_user_mode = getattr(user.profile, "user_mode", "adult") if user.profile else "adult"
    effective_user_mode = payload.user_mode.value if payload.user_mode is not None else profile_user_mode
    recent_messages = list_messages_for_thread(db, thread.id)[-RECENT_MESSAGE_CANDIDATE_LIMIT:]
    memory_mode = getattr(user.settings, "memory_mode", "summary_only") if user.settings else "summary_only"
    serialized_recent_messages = _serialize_recent_messages(recent_messages)
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
        session_digest=thread.session_digest or {},
        memory_mode=memory_mode,
        risk_level=pre_risk_level,
        limit=5,
        record_access=True,
    )
    return TurnContext(
        turn=turn,
        user_message=user_message,
        effective_user_mode=effective_user_mode,
        serialized_recent_messages=serialized_recent_messages,
        memory_mode=memory_mode,
        memory_index=memory_index,
        retrieved_memories=retrieved_memories,
        pre_risk_level=pre_risk_level,
    )


async def _persist_turn_result(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
    context: TurnContext,
    assistant_result: dict[str, object],
) -> tuple[Message | None, dict[str, object]]:
    assistant_result = _coerce_delivery_result(assistant_result, pre_risk_level=context.pre_risk_level)
    assistant_result["memory_mode"] = context.memory_mode
    assistant_result["retrieved_memory_count"] = len(context.retrieved_memories)
    delivery_status = str(assistant_result.get("delivery_status", "generated"))
    graph_trace = _pop_graph_trace(assistant_result)
    trace_summary = assistant_result.get("trace_summary", {})

    if not thread.title or thread.title == "new session":
        thread.title = payload.content[:20] if payload.content else "new session"
    thread.updated_at = utcnow()
    thread.last_risk_level = str(assistant_result.get("risk_level", context.pre_risk_level))

    if delivery_status == "failed_no_reply":
        assistant_result = _complete_turn(
            context.turn,
            user_message=context.user_message,
            assistant_message=None,
            assistant_result=assistant_result,
        )
        db.commit()
        persist_turn_traces(db, turn=context.turn, traces=graph_trace)
        db.refresh(context.user_message)
        db.refresh(context.turn)
        db.refresh(thread)
        return None, assistant_result

    assistant_metadata = {
        **_turn_metadata(context.turn),
        "intent": assistant_result.get("intent", "other"),
        "risk_reasons": assistant_result.get("risk_reasons", []),
        "semantic_risk": assistant_result.get("semantic_risk", {}),
        "risk_source": assistant_result.get("risk_source", ""),
        "risk_reason_codes": assistant_result.get("risk_reason_codes", []),
        "requires_safety_check": bool(assistant_result.get("requires_safety_check", False)),
        "suggested_actions": assistant_result.get("suggested_actions", []),
        "session_summary": assistant_result.get("session_summary", ""),
        "session_digest": assistant_result.get("session_digest", {}),
        "should_write_memory": assistant_result.get("should_write_memory", False),
        "referenced_memories": assistant_result.get("referenced_memories", []),
        "referenced_counseling_examples": assistant_result.get("referenced_counseling_examples", []),
        "memory_index": context.memory_index,
        "memory_write_decisions": [],
        "memory_policy_reason": assistant_result.get("memory_policy", ""),
        "delivery_status": delivery_status,
        "failure_reason": assistant_result.get("failure_reason"),
        "retryable": bool(assistant_result.get("retryable", False)),
        "tool_trace_summary": assistant_result.get("tool_trace_summary", {}),
        "trace_summary": trace_summary,
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
    context.turn.assistant_message_id = assistant_message.id

    thread.last_summary = str(assistant_result.get("session_summary", "") or "")
    session_digest = assistant_result.get("session_digest")
    if isinstance(session_digest, dict) and session_digest:
        thread.session_digest = session_digest

    risk_level = str(assistant_result.get("risk_level", "L0"))
    if risk_level in {"L2", "L3"}:
        _upsert_risk_event(
            db,
            user_id=user.id,
            thread_id=thread.id,
            message_id=context.user_message.id,
            risk_level=risk_level,
            trigger_text=payload.content,
            action_taken=list(assistant_result.get("suggested_actions", [])),
        )

    memory_job_id: str | None = None
    memory_job_status = "skipped"
    memory_job_payload, memory_write_decisions = build_memory_job_payload(
        assistant_result,
        memory_mode=context.memory_mode,
    )
    if memory_job_payload is not None:
        memory_job = enqueue_memory_job(
            db,
            user_id=user.id,
            thread_id=thread.id,
            turn_id=context.turn.id,
            assistant_message_id=assistant_message.id,
            payload=memory_job_payload,
        )
        memory_job_id = memory_job.id
        memory_job_status = memory_job.status
        memory_write_decisions = [
            {
                "status": memory_job.status,
                "reason": "background_memory_job",
                "job_id": memory_job.id,
            }
        ]

    assistant_result["memory_write_decisions"] = memory_write_decisions
    assistant_result["memory_job_id"] = memory_job_id
    assistant_result["memory_job_status"] = memory_job_status
    if isinstance(trace_summary, dict):
        memory_summary = dict(trace_summary.get("memory") or {}) if isinstance(trace_summary.get("memory"), dict) else {}
        memory_summary["job_status"] = memory_job_status
        if memory_job_id is not None:
            memory_summary["job_id"] = memory_job_id
        if memory_write_decisions:
            memory_summary["write_decisions"] = memory_write_decisions
            memory_summary["write_decision_count"] = len(memory_write_decisions)
        trace_summary = {**trace_summary, "memory": memory_summary}
        assistant_result["trace_summary"] = trace_summary
    assistant_message.meta = {
        **assistant_metadata,
        "memory_job_id": memory_job_id,
        "memory_job_status": memory_job_status,
        "memory_write_decisions": memory_write_decisions,
        "trace_summary": trace_summary,
    }

    assistant_result = _complete_turn(
        context.turn,
        user_message=context.user_message,
        assistant_message=assistant_message,
        assistant_result=assistant_result,
    )
    db.commit()
    persist_turn_traces(db, turn=context.turn, traces=graph_trace)
    db.refresh(context.user_message)
    db.refresh(assistant_message)
    db.refresh(context.turn)
    db.refresh(thread)
    if memory_job_id is not None:
        notify_memory_jobs()
    return assistant_message, assistant_result


def _graph_update_event(node: str, **data: object) -> ChatStreamEvent:
    return "graph_update", {"node": node, "status": "completed", **data}


def _heartbeat_event(started_at: float) -> ChatStreamEvent:
    return "heartbeat", {"status": "running", "elapsed_ms": int((monotonic() - started_at) * 1000)}


async def process_message_turn(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
) -> tuple[Message, Message | None, dict[str, object]]:
    turn_id: str | None = None
    try:
        claim = await _claim_turn(db, user=user, thread=thread, payload=payload, wait_for_running=True)
        turn_id = claim.turn.id
        if claim.replay:
            return _replay_turn_result(db, claim.turn)

        user_message = _create_user_message(db, user=user, thread=thread, payload=payload, turn=claim.turn)
        context = await _prepare_turn_context(
            db,
            user=user,
            thread=thread,
            payload=payload,
            user_message=user_message,
            turn=claim.turn,
        )
        assistant_result = await _invoke_graph_with_fallback(
            thread=thread,
            user=user,
            payload=payload,
            effective_user_mode=context.effective_user_mode,
            serialized_recent_messages=context.serialized_recent_messages,
            memory_mode=context.memory_mode,
            memory_index=context.memory_index,
            retrieved_memories=context.retrieved_memories,
            pre_risk_level=context.pre_risk_level,
        )
        assistant_message, assistant_result = await _persist_turn_result(
            db,
            user=user,
            thread=thread,
            payload=payload,
            context=context,
            assistant_result=assistant_result,
        )
        return user_message, assistant_message, assistant_result
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        _mark_turn_failed(db, turn_id, "turn_execution_failed")
        raise


async def process_message_turn_stream(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    payload: SendMessageRequest,
) -> AsyncIterator[ChatStreamEvent]:
    started_at = monotonic()
    turn_id: str | None = None
    user_message: Message | None = None
    context: TurnContext | None = None
    try:
        claim = await _claim_turn(db, user=user, thread=thread, payload=payload, wait_for_running=False)
        turn_id = claim.turn.id
        yield "accepted", {"thread_id": thread.id, "status": "accepted", **_turn_response_fields(claim.turn)}
        if claim.replay:
            replay_user_message, replay_assistant_message, replay_result = _replay_turn_result(db, claim.turn)
            if replay_assistant_message is not None:
                for chunk in _iter_stream_chunks(replay_assistant_message.content):
                    yield "token", {"text": chunk}
            yield "final", {
                "thread_id": thread.id,
                "message_id": replay_user_message.id,
                "assistant_message_id": replay_assistant_message.id if replay_assistant_message is not None else None,
                **replay_result,
            }
            return

        user_message = _create_user_message(db, user=user, thread=thread, payload=payload, turn=claim.turn)
        context = await _prepare_turn_context(
            db,
            user=user,
            thread=thread,
            payload=payload,
            user_message=user_message,
            turn=claim.turn,
        )
        yield _graph_update_event("risk_classifier", risk_level=context.pre_risk_level)
        yield _graph_update_event(
            "memory_retrieval",
            risk_level=context.pre_risk_level,
            retrieved_memory_count=len(context.retrieved_memories),
        )

        timeout_seconds = max(float(settings.chat_turn_timeout_seconds), 0.1)
        deadline = monotonic() + timeout_seconds
        graph_events = graph_runtime.stream_turn(
            thread_id=thread.langgraph_thread_id,
            user_id=user.id,
            content=payload.content,
            input_type=payload.input_type.value,
            user_mode=context.effective_user_mode,
            recent_messages=context.serialized_recent_messages,
            last_summary=thread.last_summary,
            session_digest=thread.session_digest or {},
            memory_mode=context.memory_mode,
            companion_style=getattr(user.settings, "companion_style", "") if user.settings else "",
            nickname=getattr(user.profile, "nickname", None) if user.profile else None,
            crisis_resource_region=getattr(user.settings, "crisis_resource_region", "CN") if user.settings else "CN",
            retrieved_memories=context.retrieved_memories,
            memory_index=context.memory_index,
        )
        next_event = asyncio.create_task(anext(graph_events))
        assistant_result: dict[str, object] | None = None
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    event_name, data = await asyncio.wait_for(
                        asyncio.shield(next_event),
                        timeout=min(5.0, remaining),
                    )
                except asyncio.TimeoutError:
                    if monotonic() >= deadline:
                        next_event.cancel()
                        raise
                    yield _heartbeat_event(started_at)
                    continue
                except StopAsyncIteration:
                    break
                except Exception:
                    logger.exception("Chat graph stream failed; returning delivery fallback.")
                    assistant_result = _fallback_assistant_result(
                        risk_level=context.pre_risk_level,
                        reason="graph_error_fallback",
                    )
                    break

                if event_name == "graph_result":
                    assistant_result = data
                    break
                yield event_name, data
                next_event = asyncio.create_task(anext(graph_events))
        finally:
            if not next_event.done():
                next_event.cancel()
            aclose = getattr(graph_events, "aclose", None)
            if callable(aclose):
                await aclose()

        if assistant_result is None:
            assistant_result = _fallback_assistant_result(
                risk_level=context.pre_risk_level,
                reason="graph_empty_stream_fallback",
            )
        assistant_result = _coerce_delivery_result(assistant_result, pre_risk_level=context.pre_risk_level)
        yield _graph_update_event(
            "response_validator",
            risk_level=str(assistant_result.get("risk_level", context.pre_risk_level)),
            validator_blocked=bool(assistant_result.get("validator_blocked", False)),
            delivery_status=str(assistant_result.get("delivery_status", "generated")),
        )
        yield _graph_update_event("saving_record", delivery_status=str(assistant_result.get("delivery_status", "generated")))
        assistant_message, assistant_result = await _persist_turn_result(
            db,
            user=user,
            thread=thread,
            payload=payload,
            context=context,
            assistant_result=assistant_result,
        )

        yield "final", {
            "thread_id": thread.id,
            "message_id": user_message.id,
            "assistant_message_id": assistant_message.id if assistant_message is not None else None,
            **assistant_result,
        }
    except asyncio.TimeoutError:
        logger.warning("Chat graph stream timed out; returning delivery fallback.")
        if user_message is None:
            db.rollback()
            _mark_turn_failed(db, turn_id, "stream_timeout")
            yield "error", {"message": "stream_timeout", "retryable": True, "turn_status": "failed"}
            return
        if context is None:
            turn = db.get(ConversationTurn, turn_id) if turn_id is not None else None
            if turn is None:
                db.rollback()
                yield "error", {"message": "stream_timeout", "retryable": True, "turn_status": "failed"}
                return
            context = await _prepare_turn_context(
                db,
                user=user,
                thread=thread,
                payload=payload,
                user_message=user_message,
                turn=turn,
            )
        assistant_result = _fallback_assistant_result(
            risk_level=context.pre_risk_level,
            reason="graph_timeout_fallback",
        )
        assistant_message, assistant_result = await _persist_turn_result(
            db,
            user=user,
            thread=thread,
            payload=payload,
            context=context,
            assistant_result=assistant_result,
        )
        yield "final", {
            "thread_id": thread.id,
            "message_id": user_message.id,
            "assistant_message_id": assistant_message.id if assistant_message is not None else None,
            **assistant_result,
        }
    except HTTPException as exc:
        db.rollback()
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        yield "error", {"retryable": False, **detail}
    except Exception:
        db.rollback()
        _mark_turn_failed(db, turn_id, "stream_failed")
        logger.exception("Chat stream failed.")
        yield "error", {"message": "stream_failed", "retryable": True, "turn_status": "failed"}


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
