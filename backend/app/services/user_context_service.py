from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import User, UserMemory


DIGEST_SCHEMA_VERSION = 1
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 80
GOAL_KEYWORDS = (
    "我想",
    "我希望",
    "目标",
    "计划",
    "打算",
    "先把",
    "理清楚",
    "解决",
    "要处理",
    "当前任务",
    "做到",
    "完成",
)
VAGUE_FOLLOWUP_TERMS = (
    "继续",
    "接着",
    "然后呢",
    "这个",
    "那个",
    "随便",
    "都行",
    "不知道",
    "说不清",
    "有点乱",
    "嗯",
    "好",
    "可以",
)


def _compact_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _compact_list(value: object, *, limit: int = MAX_LIST_ITEMS, item_limit: int = MAX_ITEM_CHARS) -> list[str]:
    if isinstance(value, str):
        raw_items: Iterable[object] = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = _compact_text(raw_item, limit=item_limit)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _memory_hints(db: Session, *, user_id: str) -> dict[str, list[str]]:
    hints = {
        "profile_hints": [],
        "preference_hints": [],
        "correction_hints": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in hints}
    memory_type_to_field = {
        "profile": "profile_hints",
        "preference": "preference_hints",
        "correction": "correction_hints",
    }
    query = (
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_state != "do_not_use",
            UserMemory.visibility == "user_visible",
            UserMemory.memory_type.in_(tuple(memory_type_to_field)),
        )
        .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        .limit(20)
    )
    for memory in db.scalars(query):
        field = memory_type_to_field.get(memory.memory_type)
        if field is None:
            continue
        content = _compact_text(memory.summary or memory.content, limit=MAX_ITEM_CHARS)
        if not content or content in seen[field]:
            continue
        seen[field].add(content)
        hints[field].append(content)
        if len(hints[field]) >= MAX_LIST_ITEMS:
            continue
    return hints


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata = message.get("meta")
    return metadata if isinstance(metadata, dict) else {}


def _last_assistant_message(recent_messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for message in reversed(recent_messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role == "assistant":
            return message
    return None


def _is_clarification_message(message: dict[str, Any] | None) -> bool:
    if not isinstance(message, dict):
        return False
    metadata = _message_metadata(message)
    if bool(metadata.get("clarification_needed")):
        return True
    if metadata.get("control_category") == "clarification_needed":
        return True
    content = str(message.get("content") or "")
    return content.startswith("我先确认一下") and "？" in content


def _clarification_context(recent_messages: list[dict[str, Any]] | None) -> dict[str, str] | None:
    message = _last_assistant_message(recent_messages)
    if not _is_clarification_message(message):
        return None
    assert message is not None
    metadata = _message_metadata(message)
    return {
        "clarification_reason": _compact_text(metadata.get("clarification_reason"), limit=40),
        "clarification_prompt": _compact_text(message.get("content"), limit=120),
    }


def _clarification_answer(current_text: str, recent_messages: list[dict[str, Any]] | None) -> dict[str, str]:
    context = _clarification_context(recent_messages)
    if not context:
        return {}
    compact = _compact_text(current_text, limit=MAX_ITEM_CHARS)
    normalized = "".join(compact.split())
    if not normalized or normalized in VAGUE_FOLLOWUP_TERMS:
        return {}
    return {
        **context,
        "clarification_answer": compact,
        "current_goal": f"用户澄清当前想谈：{compact}",
    }


def _goal_hints(db: Session, *, user_id: str) -> list[str]:
    query = (
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_state != "do_not_use",
            UserMemory.visibility == "user_visible",
            UserMemory.memory_type == "goal",
        )
        .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        .limit(10)
    )
    hints: list[str] = []
    seen: set[str] = set()
    for memory in db.scalars(query):
        content = _compact_text(memory.summary or memory.content, limit=MAX_ITEM_CHARS)
        if not content or content in seen:
            continue
        seen.add(content)
        hints.append(content)
        if len(hints) >= MAX_LIST_ITEMS:
            break
    return hints


def _digest_threads(session_digest: dict[str, Any] | None) -> list[str]:
    if not isinstance(session_digest, dict):
        return []
    items: list[object] = []
    for key in ("unresolved_threads", "significant_changes"):
        value = session_digest.get(key)
        if isinstance(value, list):
            items.extend(value)
        elif isinstance(value, str):
            items.append(value)
    return _compact_list(items, limit=MAX_LIST_ITEMS)


def build_user_profile_digest(db: Session, *, user_id: str) -> dict[str, Any] | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    profile = user.profile
    settings = user.settings
    digest: dict[str, Any] = {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "nickname": _compact_text(profile.nickname if profile else user.username or "user", limit=40),
        "age_range": _compact_text(profile.age_range if profile else "", limit=24),
        "user_mode": _compact_text(profile.user_mode if profile else "adult", limit=16),
        "usage_goals": _compact_list(profile.usage_goals if profile else [], limit=MAX_LIST_ITEMS),
        "communication_preferences": _compact_list(
            [settings.companion_style] if settings and settings.companion_style else [],
            limit=MAX_LIST_ITEMS,
        ),
        "profile_hints": [],
        "preference_hints": [],
        "correction_hints": [],
    }

    digest.update(_memory_hints(db, user_id=user_id))

    if not any(
        digest[field]
        for field in (
            "nickname",
            "age_range",
            "user_mode",
            "usage_goals",
            "communication_preferences",
            "profile_hints",
            "preference_hints",
            "correction_hints",
        )
    ):
        return None
    return digest


def build_goal_state(
    db: Session,
    *,
    user_id: str,
    current_text: str = "",
    session_digest: dict[str, Any] | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    user = db.get(User, user_id)
    if user is None:
        return None

    profile = user.profile
    compact_current = _compact_text(current_text, limit=MAX_ITEM_CHARS)
    clarification = _clarification_answer(compact_current, recent_messages)
    current_goal = clarification.get("current_goal") or (
        compact_current if compact_current and _contains_any(compact_current, GOAL_KEYWORDS) else ""
    )
    goal_state: dict[str, Any] = {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "current_goal": current_goal,
        "usage_goals": _compact_list(profile.usage_goals if profile else [], limit=MAX_LIST_ITEMS),
        "goal_hints": _goal_hints(db, user_id=user_id),
        "open_threads": _digest_threads(session_digest),
        "clarification_answer": clarification.get("clarification_answer", ""),
        "clarification_reason": clarification.get("clarification_reason", ""),
        "clarification_prompt": clarification.get("clarification_prompt", ""),
    }

    if not any(
        goal_state[field]
        for field in (
            "current_goal",
            "usage_goals",
            "goal_hints",
            "open_threads",
            "clarification_answer",
        )
    ):
        return None
    return goal_state
