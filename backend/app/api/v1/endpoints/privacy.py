from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.privacy import AccountDeleteRequest, DataDeleteRequest, PrivacyMutationResponse, PrivacySummaryResponse
from app.services.privacy_service import build_privacy_summary, build_user_data_export, delete_account, delete_user_data

router = APIRouter(prefix="/me", tags=["privacy"])


@router.get("/privacy-summary", response_model=PrivacySummaryResponse)
async def privacy_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PrivacySummaryResponse:
    return build_privacy_summary(db, current_user)


@router.get("/data-export")
async def data_export(
    format: str = Query(default="json", pattern="^json$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    return build_user_data_export(db, current_user)


@router.delete("/data", response_model=PrivacyMutationResponse)
async def delete_data(
    payload: DataDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PrivacyMutationResponse:
    return delete_user_data(db, current_user, scope=payload.scope)


@router.delete("/account", response_model=PrivacyMutationResponse)
async def delete_current_account(
    payload: AccountDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PrivacyMutationResponse:
    # The schema enforces the explicit confirmation string.
    _ = payload
    return delete_account(db, current_user)
