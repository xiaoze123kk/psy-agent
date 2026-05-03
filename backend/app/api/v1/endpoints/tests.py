from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
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
) -> TestHistoryResponse:
    return get_history(current_user.id)


@router.get("", response_model=TestListResponse)
async def list_tests() -> TestListResponse:
    return get_tests()


@router.get("/{test_id}", response_model=TestDetailResponse)
async def read_test(test_id: str) -> TestDetailResponse:
    result = get_test(test_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found.")
    return result


@router.post("/{test_id}/attempts", response_model=StartAttemptResponse)
async def start_test_attempt(
    test_id: str,
    current_user: User = Depends(get_current_user),
) -> StartAttemptResponse:
    result = start_attempt(current_user.id, test_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found.")
    return result


@router.post("/attempts/{attempt_id}/answers", response_model=AnswerResponse)
async def answer_question(
    attempt_id: str,
    payload: SubmitAnswerRequest,
    current_user: User = Depends(get_current_user),
) -> AnswerResponse:
    ok = submit_answer(attempt_id, payload.question_index, payload.option_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attempt or answer.")
    return AnswerResponse(ok=True)


@router.post("/attempts/{attempt_id}/complete", response_model=CompleteAttemptResponse)
async def finish_attempt(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
) -> CompleteAttemptResponse:
    result = complete_attempt(attempt_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt not found, already completed, or not all questions answered.",
        )
    return result
