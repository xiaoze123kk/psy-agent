from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.db.models import User
from app.schemas.tests import (
    AnswerResponse,
    CompleteAttemptResponse,
    StartAttemptResponse,
    SubmitAnswerRequest,
    TestDetailResponse,
    TestHistoryResponse,
    TestListResponse,
)
from app.services.test_service import (
    complete_attempt,
    get_attempt_result,
    get_history,
    get_test,
    get_tests,
    start_attempt,
    submit_answer,
)

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("/history", response_model=TestHistoryResponse)
async def test_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> TestHistoryResponse:
    return get_history(current_user.id, db)


@router.get("", response_model=TestListResponse)
async def list_tests() -> TestListResponse:
    return get_tests()


@router.get("/{test_id}", response_model=TestDetailResponse)
async def read_test(test_id: str) -> TestDetailResponse:
    result = get_test(test_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found.")
    return result


@router.get("/attempts/{attempt_id}/result", response_model=CompleteAttemptResponse)
async def read_attempt_result(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompleteAttemptResponse:
    result = get_attempt_result(attempt_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found or not completed.")
    return result


@router.post("/{test_id}/attempts", response_model=StartAttemptResponse)
async def start_test_attempt(
    test_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StartAttemptResponse:
    result = start_attempt(current_user.id, test_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found.")
    return result


@router.post("/attempts/{attempt_id}/answers", response_model=AnswerResponse)
async def answer_question(
    attempt_id: str,
    payload: SubmitAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AnswerResponse:
    ok = submit_answer(attempt_id, payload.question_index, payload.option_id, db)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attempt or answer.")
    return AnswerResponse(ok=True)


@router.post("/attempts/{attempt_id}/complete", response_model=CompleteAttemptResponse)
async def finish_attempt(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CompleteAttemptResponse:
    result = complete_attempt(attempt_id, db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt not found, already completed, or not all questions answered.",
        )
    return result
