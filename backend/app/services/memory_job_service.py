from __future__ import annotations

import asyncio
import json
import logging
import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ConversationThread, ConversationTurn, Message, PendingMemoryJob, User, utcnow
from app.db.session import SessionLocal
from app.services.memory_service import (
    index_memory_embeddings,
    maybe_auto_consolidate_user_memories,
    upsert_memory_candidates,
)


logger = logging.getLogger(__name__)

MEMORY_WRITE_JOB_TYPE = "memory_write"
_worker_task: asyncio.Task | None = None
_wake_event: asyncio.Event | None = None


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def _short_error(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    return text[:500]


def build_memory_job_payload(
    assistant_result: dict[str, object],
    *,
    memory_mode: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    if not bool(assistant_result.get("should_write_memory")):
        return None, [{"status": "skipped", "reason": "assistant_result_disabled"}]

    risk_level = str(assistant_result.get("risk_level", "L0"))
    memory_policy = str(assistant_result.get("memory_policy", "write_safe_summary"))
    if memory_mode == "off" and risk_level not in {"L2", "L3"}:
        return None, [{"status": "skipped", "reason": "memory_mode_off"}]
    if memory_policy == "skip_sensitive" and risk_level not in {"L2", "L3"}:
        return None, [{"status": "skipped", "reason": "memory_policy_skip_sensitive"}]

    memory_candidates = [
        dict(candidate)
        for candidate in assistant_result.get("memory_candidates", [])
        if isinstance(candidate, dict) and _clean_text(candidate.get("content"))
    ]
    session_summary = _clean_text(assistant_result.get("session_summary"))
    if not memory_candidates and not session_summary:
        return None, [{"status": "skipped", "reason": "no_candidates"}]

    return (
        {
            "should_write_memory": True,
            "memory_candidates": _json_safe(memory_candidates),
            "session_summary": session_summary,
            "risk_level": risk_level,
            "memory_policy": memory_policy,
            "memory_mode": memory_mode,
        },
        [],
    )


def enqueue_memory_job(
    db: Session,
    *,
    user_id: str,
    thread_id: str,
    turn_id: str,
    assistant_message_id: str,
    payload: dict[str, object],
    max_attempts: int | None = None,
) -> PendingMemoryJob:
    existing = db.scalar(
        select(PendingMemoryJob).where(
            PendingMemoryJob.turn_id == turn_id,
            PendingMemoryJob.job_type == MEMORY_WRITE_JOB_TYPE,
        )
    )
    if existing is not None:
        return existing

    job = PendingMemoryJob(
        user_id=user_id,
        thread_id=thread_id,
        turn_id=turn_id,
        assistant_message_id=assistant_message_id,
        job_type=MEMORY_WRITE_JOB_TYPE,
        status="pending",
        max_attempts=max_attempts or max(int(settings.memory_job_max_attempts), 1),
        next_run_at=utcnow(),
        payload=_json_safe(payload),
    )
    db.add(job)
    db.flush()
    return job


def claim_pending_memory_jobs(
    db: Session,
    *,
    limit: int | None = None,
    worker_id: str | None = None,
) -> list[PendingMemoryJob]:
    now = utcnow()
    batch_size = max(int(limit or settings.memory_job_batch_size), 1)
    jobs = list(
        db.scalars(
            select(PendingMemoryJob)
            .where(
                PendingMemoryJob.job_type == MEMORY_WRITE_JOB_TYPE,
                PendingMemoryJob.status == "pending",
                PendingMemoryJob.next_run_at <= now,
            )
            .order_by(PendingMemoryJob.created_at)
            .limit(batch_size)
        )
    )
    for job in jobs:
        job.status = "running"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.locked_at = now
        job.locked_by = worker_id or socket.gethostname()
        job.updated_at = now
    db.commit()
    return jobs


def _set_assistant_memory_metadata(
    assistant_message: Message | None,
    *,
    job: PendingMemoryJob,
    status: str,
    decisions: list[dict[str, object]],
) -> None:
    if assistant_message is None:
        return
    assistant_message.meta = {
        **(assistant_message.meta or {}),
        "memory_job_id": job.id,
        "memory_job_status": status,
        "memory_write_decisions": decisions,
    }


def _set_turn_memory_snapshot(
    turn: ConversationTurn | None,
    *,
    job: PendingMemoryJob,
    status: str,
    decisions: list[dict[str, object]],
) -> None:
    if turn is None:
        return
    turn.response_snapshot = {
        **(turn.response_snapshot or {}),
        "memory_job_id": job.id,
        "memory_job_status": status,
        "memory_write_decisions": decisions,
    }
    turn.updated_at = utcnow()


def _retry_delay(attempt_count: int) -> timedelta:
    delay_seconds = min(60, 2 ** max(attempt_count - 1, 0))
    return timedelta(seconds=delay_seconds)


def _mark_job_failed(db: Session, job_id: str, error: BaseException) -> PendingMemoryJob | None:
    job = db.get(PendingMemoryJob, job_id)
    if job is None:
        return None
    now = utcnow()
    job.last_error = _short_error(error)
    job.locked_at = None
    job.locked_by = None
    job.updated_at = now
    if int(job.attempt_count or 0) >= int(job.max_attempts or 1):
        job.status = "failed"
        job.next_run_at = now
    else:
        job.status = "pending"
        job.next_run_at = now + _retry_delay(int(job.attempt_count or 0))

    assistant_message = db.get(Message, job.assistant_message_id) if job.assistant_message_id else None
    turn = db.get(ConversationTurn, job.turn_id)
    _set_assistant_memory_metadata(
        assistant_message,
        job=job,
        status=job.status,
        decisions=[{"status": job.status, "reason": "background_memory_job_failed"}],
    )
    _set_turn_memory_snapshot(
        turn,
        job=job,
        status=job.status,
        decisions=[{"status": job.status, "reason": "background_memory_job_failed"}],
    )
    db.commit()
    return job


async def process_memory_job(db: Session, job_id: str) -> PendingMemoryJob | None:
    job = db.get(PendingMemoryJob, job_id)
    if job is None:
        return None
    if job.job_type != MEMORY_WRITE_JOB_TYPE:
        raise ValueError(f"Unsupported memory job type: {job.job_type}")

    if job.status != "running":
        job.status = "running"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.locked_at = utcnow()
        job.locked_by = socket.gethostname()
        job.updated_at = utcnow()
        db.flush()

    try:
        with db.begin_nested():
            user = db.get(User, job.user_id)
            thread = db.get(ConversationThread, job.thread_id)
            assistant_message = db.get(Message, job.assistant_message_id) if job.assistant_message_id else None
            if user is None:
                raise ValueError("Memory job user is missing.")
            if thread is None:
                raise ValueError("Memory job thread is missing.")
            if assistant_message is None:
                raise ValueError("Memory job assistant message is missing.")

            payload = dict(job.payload or {})
            assistant_result = {
                "should_write_memory": bool(payload.get("should_write_memory", True)),
                "memory_candidates": payload.get("memory_candidates", []),
                "session_summary": payload.get("session_summary", ""),
                "risk_level": payload.get("risk_level", "L0"),
                "memory_policy": payload.get("memory_policy", "write_safe_summary"),
            }
            written_memories, decisions = upsert_memory_candidates(
                db,
                user=user,
                thread=thread,
                assistant_message_id=assistant_message.id,
                assistant_result=assistant_result,
                memory_mode_override=str(payload.get("memory_mode") or "summary_only"),
            )
            await index_memory_embeddings(db, written_memories)
            consolidation_result = maybe_auto_consolidate_user_memories(db, user_id=user.id)

            job.status = "completed"
            job.result = _json_safe(
                {
                    "memory_ids": [memory.id for memory in written_memories],
                    "memory_write_decisions": decisions,
                    "written_count": len(written_memories),
                    "consolidation_result": consolidation_result,
                }
            )
            job.last_error = None
            job.locked_at = None
            job.locked_by = None
            job.updated_at = utcnow()
            turn = db.get(ConversationTurn, job.turn_id)
            _set_assistant_memory_metadata(
                assistant_message,
                job=job,
                status="completed",
                decisions=decisions,
            )
            _set_turn_memory_snapshot(
                turn,
                job=job,
                status="completed",
                decisions=decisions,
            )
        db.commit()
        return job
    except Exception as exc:
        logger.exception("Memory background job failed.", extra={"memory_job_id": job_id})
        return _mark_job_failed(db, job_id, exc)


async def process_pending_memory_jobs(db: Session | None = None, *, limit: int | None = None) -> int:
    worker_id = socket.gethostname()
    if db is not None:
        jobs = claim_pending_memory_jobs(db, limit=limit, worker_id=worker_id)
        for job in jobs:
            await process_memory_job(db, job.id)
        return len(jobs)

    with SessionLocal() as session:
        jobs = claim_pending_memory_jobs(session, limit=limit, worker_id=worker_id)
        for job in jobs:
            await process_memory_job(session, job.id)
        return len(jobs)


def notify_memory_jobs() -> None:
    if _wake_event is not None:
        _wake_event.set()


async def _memory_job_worker_loop() -> None:
    assert _wake_event is not None
    interval = max(float(settings.memory_job_poll_interval_seconds), 0.2)
    while True:
        try:
            processed = await process_pending_memory_jobs()
            if processed:
                continue
            try:
                await asyncio.wait_for(_wake_event.wait(), timeout=interval)
                _wake_event.clear()
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Memory background worker loop failed.")
            await asyncio.sleep(interval)


def start_memory_job_worker() -> asyncio.Task | None:
    global _wake_event, _worker_task
    if not settings.memory_background_worker_enabled:
        return None
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _wake_event = asyncio.Event()
    _worker_task = loop.create_task(_memory_job_worker_loop())
    return _worker_task


async def stop_memory_job_worker() -> None:
    global _wake_event, _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
    _wake_event = None
