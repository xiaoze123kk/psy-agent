from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TestListItem(BaseModel):
    test_id: str
    code: str
    title: str
    test_type: Literal["state", "personality", "anime"]
    estimated_minutes: int
    audience: str
    status: str


class TestListResponse(BaseModel):
    items: list[TestListItem]


class TestOption(BaseModel):
    id: str
    text: str
    score: int


class TestQuestion(BaseModel):
    index: int
    text: str
    options: list[TestOption]


class TestDetailResponse(BaseModel):
    test_id: str
    code: str
    title: str
    questions: list[TestQuestion]


class StartAttemptResponse(BaseModel):
    attempt_id: str
    test_id: str
    questions: list[TestQuestion]


class SubmitAnswerRequest(BaseModel):
    question_index: int
    option_id: str


class AnswerResponse(BaseModel):
    ok: bool


class TestResultProfile(BaseModel):
    sixteen_type_code: str | None = None
    sixteen_type_label: str | None = None
    traits: list[str]
    strengths: list[str]
    blind_spots: list[str]
    companion_style: str


class ContinueChatContext(BaseModel):
    mode: str = "test"
    context_type: str = "test_result"


class CompleteAttemptResponse(BaseModel):
    attempt_id: str
    test_code: str
    result_code: str
    result_title: str
    summary: str
    strengths: list[str]
    blind_spots: list[str]
    suggested_actions: list[str]
    continue_chat_context: ContinueChatContext
    profile: TestResultProfile


class TestHistoryItem(BaseModel):
    attempt_id: str
    test_id: str
    test_title: str
    result_code: str
    result_label: str
    completed_at: datetime


class TestHistoryResponse(BaseModel):
    items: list[TestHistoryItem]
