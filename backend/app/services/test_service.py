from __future__ import annotations

import base64
import importlib
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.db.models import TestAttempt, TestHistory
from app.schemas.tests import (
    CompleteAttemptResponse,
    ContinueChatContext,
    StartAttemptResponse,
    TestDetailResponse,
    TestHistoryItem,
    TestHistoryResponse,
    TestListItem,
    TestListResponse,
    TestOption,
    TestQuestion,
    TestResultProfile,
)

logger = logging.getLogger(__name__)

_TESTS_DIR = BASE_DIR / "data" / "tests"
_TEST_CATEGORIES = ["state", "personality", "anime"]


def _load_test(test_id: str) -> dict | None:
    for category in _TEST_CATEGORIES:
        test_dir = _TESTS_DIR / category / test_id
        if not test_dir.is_dir():
            continue
        title_files = list(test_dir.glob("*title*.json"))
        if not title_files:
            continue
        try:
            return json.loads(title_files[0].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load test file %s: %s", title_files[0], exc)
            return None
    return None


def _load_all_tests() -> list[dict]:
    tests: list[dict] = []
    for category in _TEST_CATEGORIES:
        category_dir = _TESTS_DIR / category
        if not category_dir.is_dir():
            continue
        for test_dir in sorted(category_dir.iterdir()):
            if not test_dir.is_dir():
                continue
            title_files = list(test_dir.glob("*title*.json"))
            if not title_files:
                continue
            try:
                data = json.loads(title_files[0].read_text(encoding="utf-8"))
                tests.append(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load test file %s: %s", title_files[0], exc)
    return tests


def _load_scorer(test_type: str, test_id: str):
    module_path = f"data.tests.{test_type}.{test_id}.scorer"
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        logger.error("Failed to load scorer %s: %s", module_path, exc)
        return None


def _normalize_answers(raw_answers: dict) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for idx_key, option_id in raw_answers.items():
        try:
            normalized[int(idx_key)] = option_id
        except (TypeError, ValueError):
            logger.warning("Skipping malformed answer key %r", idx_key)
    return normalized


def _question_to_schema(q: dict) -> TestQuestion:
    return TestQuestion(
        index=q["index"],
        text=q["text"],
        options=[TestOption(id=opt["id"], text=opt["text"], score=opt.get("score", 0)) for opt in q["options"]],
    )


def _build_shuffled_questions(questions: list[dict], seed: str) -> list[dict]:
    rng = random.Random(seed)
    order = list(range(len(questions)))
    rng.shuffle(order)
    shuffled = []
    for new_idx, old_idx in enumerate(order):
        q = dict(questions[old_idx])
        q["index"] = new_idx
        shuffled.append(q)
    return shuffled


def _remap_answer_index(attempt_id: str, shuffled_index: int, question_count: int) -> int | None:
    rng = random.Random(attempt_id)
    order = list(range(question_count))
    rng.shuffle(order)
    for new_idx, old_idx in enumerate(order):
        if new_idx == shuffled_index:
            return old_idx
    return None


def _load_result_image_base64(test_type: str, test_id: str, result_code: str) -> str | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        image_path = _TESTS_DIR / test_type / test_id / "result_image" / f"{result_code}{ext}"
        if image_path.is_file():
            try:
                raw = image_path.read_bytes()
                encoded = base64.b64encode(raw).decode("ascii")
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
                mime = mime_map.get(ext, "image/png")
                return f"data:{mime};base64,{encoded}"
            except OSError as exc:
                logger.error("Failed to read result image %s: %s", image_path, exc)
                return None
    return None


def get_tests() -> TestListResponse:
    items = [
        TestListItem(
            test_id=t["test_id"],
            code=t["code"],
            title=t["title"],
            test_type=t["test_type"],
            estimated_minutes=t["estimated_minutes"],
            audience=t["audience"],
            status=t["status"],
        )
        for t in _load_all_tests()
    ]
    return TestListResponse(items=items)


def _find_test(test_id: str) -> dict | None:
    return _load_test(test_id)


def get_test(test_id: str) -> TestDetailResponse | None:
    t = _find_test(test_id)
    if t is None:
        return None
    return TestDetailResponse(
        test_id=t["test_id"],
        code=t["code"],
        title=t["title"],
        questions=[_question_to_schema(q) for q in t["questions"]],
    )


def start_attempt(user_id: str, test_id: str, db: Session) -> StartAttemptResponse | None:
    t = _find_test(test_id)
    if t is None:
        return None
    attempt = TestAttempt(user_id=user_id, test_id=test_id)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    shuffled = _build_shuffled_questions(t["questions"], attempt.id)
    return StartAttemptResponse(
        attempt_id=attempt.id,
        test_id=test_id,
        questions=[_question_to_schema(q) for q in shuffled],
    )


def submit_answer(attempt_id: str, question_index: int, option_id: str, db: Session) -> bool:
    attempt = db.scalar(select(TestAttempt).where(TestAttempt.id == attempt_id))
    if attempt is None or attempt.status != "in_progress":
        return False
    t = _find_test(attempt.test_id)
    if t is None:
        return False
    original_index = _remap_answer_index(attempt_id, question_index, len(t["questions"]))
    if original_index is None:
        return False
    question = t["questions"][original_index]
    options = question.get("options")
    if not isinstance(options, list) or not options:
        logger.error("Malformed test question %s for test %s", original_index, attempt.test_id)
        return False
    valid_options = {opt["id"] for opt in options if isinstance(opt, dict) and "id" in opt}
    if not valid_options:
        logger.error("Malformed option set for question %s in test %s", original_index, attempt.test_id)
        return False
    if option_id not in valid_options:
        return False
    answers = dict(attempt.answers)
    answers[original_index] = option_id
    attempt.answers = answers
    db.commit()
    return True


def complete_attempt(attempt_id: str, db: Session) -> CompleteAttemptResponse | None:
    attempt = db.scalar(select(TestAttempt).where(TestAttempt.id == attempt_id))
    if attempt is None or attempt.status != "in_progress":
        return None
    t = _find_test(attempt.test_id)
    if t is None:
        return None
    expected_count = len(t["questions"])
    if len(attempt.answers) < expected_count:
        return None

    scorer = _load_scorer(t["test_type"], t["test_id"])
    if scorer is None:
        return None
    result_data = scorer.compute(t, _normalize_answers(attempt.answers))
    profile_data = result_data

    now = datetime.now(timezone.utc)
    attempt.status = "completed"
    attempt.completed_at = now
    attempt.result_code = result_data["result_code"]
    attempt.result_label = result_data["result_label"]

    history = TestHistory(
        user_id=attempt.user_id,
        attempt_id=attempt_id,
        test_id=attempt.test_id,
        test_title=t["title"],
        result_code=result_data["result_code"],
        result_label=result_data["result_label"],
        completed_at=now,
    )
    db.add(history)
    db.commit()

    return CompleteAttemptResponse(
        attempt_id=attempt_id,
        test_code=t["code"],
        test_type=t["test_type"],
        result_code=result_data["result_code"],
        result_title=result_data["result_label"],
        summary=result_data["summary"],
        strengths=profile_data.get("strengths", []),
        blind_spots=profile_data.get("blind_spots", []),
        suggested_actions=result_data.get("suggested_actions", []),
        continue_chat_context=ContinueChatContext(mode="test", context_type="test_result"),
        profile=TestResultProfile(
            sixteen_type_code=profile_data.get("sixteen_type_code"),
            sixteen_type_label=profile_data.get("sixteen_type_label"),
            traits=profile_data.get("traits", []),
            strengths=profile_data.get("strengths", []),
            blind_spots=profile_data.get("blind_spots", []),
            companion_style=profile_data.get("companion_style", ""),
        ),
    )


def get_attempt_result(attempt_id: str, db: Session) -> CompleteAttemptResponse | None:
    attempt = db.scalar(select(TestAttempt).where(TestAttempt.id == attempt_id))
    if attempt is None or attempt.status != "completed":
        return None
    t = _find_test(attempt.test_id)
    if t is None:
        return None
    scorer = _load_scorer(t["test_type"], t["test_id"])
    if scorer is None:
        return None
    result_data = scorer.compute(t, _normalize_answers(attempt.answers))
    profile_data = result_data
    result_image = _load_result_image_base64(t["test_type"], t["test_id"], result_data["result_code"])
    return CompleteAttemptResponse(
        attempt_id=attempt_id,
        test_code=t["code"],
        test_type=t["test_type"],
        result_code=attempt.result_code or result_data["result_code"],
        result_title=attempt.result_label or result_data["result_label"],
        summary=result_data["summary"],
        strengths=profile_data.get("strengths", []),
        blind_spots=profile_data.get("blind_spots", []),
        suggested_actions=result_data.get("suggested_actions", []),
        continue_chat_context=ContinueChatContext(mode="test", context_type="test_result"),
        profile=TestResultProfile(
            sixteen_type_code=profile_data.get("sixteen_type_code"),
            sixteen_type_label=profile_data.get("sixteen_type_label"),
            traits=profile_data.get("traits", []),
            strengths=profile_data.get("strengths", []),
            blind_spots=profile_data.get("blind_spots", []),
            companion_style=profile_data.get("companion_style", ""),
        ),
        result_image_base64=result_image,
    )


def get_history(user_id: str, db: Session) -> TestHistoryResponse:
    rows = db.scalars(
        select(TestHistory)
        .where(TestHistory.user_id == user_id)
        .order_by(TestHistory.completed_at.desc())
    ).all()
    items = [
        TestHistoryItem(
            attempt_id=h.attempt_id,
            test_id=h.test_id,
            test_title=h.test_title,
            result_code=h.result_code,
            result_label=h.result_label,
            completed_at=h.completed_at,
        )
        for h in rows
    ]
    return TestHistoryResponse(items=items)
