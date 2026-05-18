from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.compact_debug import CompactDebugResponse, CompactPreviewRequest, CompactPreviewResponse
from app.services.chat_service import get_thread_for_user, list_messages_for_thread
from app.services.compact_debug_service import build_compact_debug_view, build_manual_compact_preview


router = APIRouter(prefix="/chat", tags=["compact-debug"])


def _serialize_message(message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "input_type": message.input_type,
        "risk_level": message.risk_level,
        "metadata": message.meta or {},
        "created_at": message.created_at.isoformat(),
    }


@router.get("/threads/{thread_id}/compact/debug", response_model=CompactDebugResponse)
async def get_compact_debug(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompactDebugResponse:
    thread = get_thread_for_user(db, current_user.id, thread_id)
    messages = [_serialize_message(message) for message in list_messages_for_thread(db, thread.id)]
    return CompactDebugResponse(
        **build_compact_debug_view(
            recent_messages=messages,
            session_digest=thread.session_digest or {},
            risk_level=thread.last_risk_level or "L0",
        )
    )

@router.post("/threads/{thread_id}/compact/preview", response_model=CompactPreviewResponse)
async def preview_compact(
    thread_id: str,
    payload: CompactPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompactPreviewResponse:
    thread = get_thread_for_user(db, current_user.id, thread_id)
    messages = [_serialize_message(message) for message in list_messages_for_thread(db, thread.id)]
    return CompactPreviewResponse(
        **build_manual_compact_preview(
            recent_messages=messages,
            session_digest=thread.session_digest or {},
            risk_level=thread.last_risk_level or "L0",
            focus=payload.focus,
            max_recent_messages=payload.max_recent_messages,
        )
    )
