from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import User, UserMemory


DIGEST_SCHEMA_VERSION = 1
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 80


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
