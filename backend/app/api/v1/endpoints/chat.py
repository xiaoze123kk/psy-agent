from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import ConversationThread, User
from app.db.session import get_db_session
from app.schemas.chat import (
    AssistantMessageResponse,
    MessageItemResponse,
    MessageListResponse,
    SendMessageRequest,
    SendMessageResponse,
    StartThreadRequest,
    StartThreadResponse,
    ThreadListItem,
    ThreadListResponse,
)
from app.services.chat_service import (
    get_thread_for_user,
    list_messages_for_thread,
    list_threads_for_user,
    process_message_turn,
    process_message_turn_stream,
)


router = APIRouter(prefix="/chat", tags=["chat"])


def format_sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def iter_stream_chunks(text: str, *, chunk_size: int = 6):
    buffer = ""
    stop_chars = set("。！？!?；;\n")
    for char in text:
        buffer += char
        if len(buffer) >= chunk_size or char in stop_chars:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer


def build_send_message_response(
    *,
    thread_id: str,
    user_message_id: str,
    assistant_message,
    assistant_result: dict[str, object],
) -> SendMessageResponse:
    if assistant_message is None:
        return SendMessageResponse(
            thread_id=thread_id,
            message_id=user_message_id,
            assistant_message_id=None,
            client_message_id=assistant_result.get("client_message_id"),
            turn_id=assistant_result.get("turn_id"),
            turn_status=str(assistant_result.get("turn_status", "completed")),
            assistant_message=None,
            delivery_status=str(assistant_result.get("delivery_status", "failed_no_reply")),
            failure_reason=assistant_result.get("failure_reason"),
            retryable=bool(assistant_result.get("retryable", False)),
        )

    return SendMessageResponse(
        thread_id=thread_id,
        message_id=user_message_id,
        assistant_message_id=assistant_message.id,
        client_message_id=assistant_result.get("client_message_id"),
        turn_id=assistant_result.get("turn_id"),
        turn_status=str(assistant_result.get("turn_status", "completed")),
        assistant_message=AssistantMessageResponse(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            assistant_text=assistant_message.content,
            risk_level=assistant_result["risk_level"],
            intent=str(assistant_result.get("intent", "other")),
            suggested_actions=list(assistant_result.get("suggested_actions", [])),
            session_summary=str(assistant_result.get("session_summary", "")),
            should_write_memory=bool(assistant_result.get("should_write_memory", False)),
            referenced_memories=list(assistant_result.get("referenced_memories", [])),
            referenced_counseling_examples=list(
                assistant_result.get("referenced_counseling_examples", [])
            ),
            delivery_status=str(assistant_result.get("delivery_status", "generated")),
            failure_reason=assistant_result.get("failure_reason"),
            retryable=bool(assistant_result.get("retryable", False)),
            created_at=assistant_message.created_at,
        ),
        delivery_status=str(assistant_result.get("delivery_status", "generated")),
        failure_reason=assistant_result.get("failure_reason"),
        retryable=bool(assistant_result.get("retryable", False)),
    )


@router.post("/threads", response_model=StartThreadResponse)
async def create_thread(
    payload: StartThreadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StartThreadResponse:
    thread_id = str(uuid4())
    langgraph_thread_id = f"lg-{thread_id}"
    thread = ConversationThread(
        id=thread_id,
        user_id=current_user.id,
        langgraph_thread_id=langgraph_thread_id,
        mode=payload.mode.value,
        title=payload.title or "new session",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return StartThreadResponse(
        thread_id=thread.id,
        langgraph_thread_id=thread.langgraph_thread_id,
        mode=thread.mode,
        title=thread.title or "new session",
        updated_at=thread.updated_at,
    )


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ThreadListResponse:
    threads = list_threads_for_user(db, current_user.id)
    return ThreadListResponse(
        items=[
            ThreadListItem(
                thread_id=thread.id,
                title=thread.title or "new session",
                mode=thread.mode,
                last_summary=thread.last_summary,
                last_risk_level=thread.last_risk_level,
                updated_at=thread.updated_at,
            )
            for thread in threads
        ]
    )


@router.get("/threads/{thread_id}/messages", response_model=MessageListResponse)
async def get_messages(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MessageListResponse:
    thread = get_thread_for_user(db, current_user.id, thread_id)
    messages = list_messages_for_thread(db, thread.id)
    return MessageListResponse(
        items=[
            MessageItemResponse(
                id=message.id,
                role=message.role,
                content=message.content,
                input_type=message.input_type,
                risk_level=message.risk_level,
                metadata=message.meta or {},
                created_at=message.created_at,
            )
            for message in messages
        ]
    )


@router.post("/threads/{thread_id}/messages", response_model=SendMessageResponse)
async def send_message(
    thread_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SendMessageResponse:
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payload user_id does not match the authenticated user.",
        )

    thread = get_thread_for_user(db, current_user.id, thread_id)
    user_message, assistant_message, assistant_result = await process_message_turn(
        db,
        user=current_user,
        thread=thread,
        payload=payload,
    )
    return build_send_message_response(
        thread_id=thread.id,
        user_message_id=user_message.id,
        assistant_message=assistant_message,
        assistant_result=assistant_result,
    )


@router.post("/threads/{thread_id}/stream")
async def stream_message(
    thread_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    if payload.user_id is not None and payload.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payload user_id does not match the authenticated user.",
        )

    thread = get_thread_for_user(db, current_user.id, thread_id)

    async def event_generator():
        async for event, data in process_message_turn_stream(
            db,
            user=current_user,
            thread=thread,
            payload=payload,
        ):
            yield format_sse_event(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
