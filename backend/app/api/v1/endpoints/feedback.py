from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User, UserFeedback
from app.db.session import get_db_session
from app.schemas.feedback import FeedbackCreateRequest, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> FeedbackResponse:
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
