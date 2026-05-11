from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import Message, User
from app.db.session import get_db_session
from app.schemas.common import SafetyAudience
from app.schemas.safety import (
    CrisisEventRequest,
    CrisisEventResponse,
    SafetyResourceItem,
    SafetyResourcesResponse,
)
from app.services.chat_service import create_or_get_risk_event, get_thread_for_user
from app.services.safety_service import build_safety_resources


router = APIRouter(prefix="/safety", tags=["safety"])


def _build_resources(region: str, audience: SafetyAudience) -> list[SafetyResourceItem]:
    common_items = [
        SafetyResourceItem(
            resource_type="trusted_person",
            title="联系现实中的可信任对象",
            description="优先联系家人、朋友、同住人，或此刻能到场陪你的人，不要一个人扛着。",
        ),
        SafetyResourceItem(
            resource_type="emergency",
            title="必要时联系当地紧急服务",
            description=f"如果你在 {region} 且已经处于紧急危险，请立刻联系当地急救或报警资源。",
        ),
    ]
    teen_items = [
        SafetyResourceItem(
            resource_type="school",
            title="联系可信任的大人",
            description="优先联系监护人、班主任、任课老师、学校心理老师或辅导员。",
        )
    ]
    adult_items = [
        SafetyResourceItem(
            resource_type="adult_support",
            title="联系成年支持系统",
            description="联系伴侣、家人、朋友、同事，或尽快寻求线下专业支持。",
        )
    ]
    if audience == SafetyAudience.teen:
        return teen_items + common_items
    if audience == SafetyAudience.adult:
        return adult_items + common_items
    return common_items


@router.get("/resources", response_model=SafetyResourcesResponse)
async def safety_resources(
    region: str = "CN",
    audience: SafetyAudience = SafetyAudience.all,
) -> SafetyResourcesResponse:
    return build_safety_resources(region=region, audience=audience)


@router.post("/crisis-events", response_model=CrisisEventResponse)
async def create_crisis_event(
    payload: CrisisEventRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CrisisEventResponse:
    if payload.risk_level.value not in {"L2", "L3"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only L2/L3 risk events can be recorded.",
        )

    thread = get_thread_for_user(db, current_user.id, payload.thread_id)
    trigger_text = " / ".join(payload.detected_signals) if payload.detected_signals else payload.risk_level.value
    if payload.message_id is not None:
        message = db.scalar(
            select(Message).where(
                Message.id == payload.message_id,
                Message.thread_id == thread.id,
                Message.user_id == current_user.id,
            )
        )
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found for this thread.",
            )
        trigger_text = message.content

    event = create_or_get_risk_event(
        db,
        user_id=current_user.id,
        thread_id=thread.id,
        message_id=payload.message_id,
        risk_level=payload.risk_level.value,
        trigger_text=trigger_text,
        action_taken=list(payload.action_taken),
    )
    return CrisisEventResponse(event_id=event.id, thread_id=thread.id, status="recorded")
