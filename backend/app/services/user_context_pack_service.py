from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = 1
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 90
HIGH_RISK_LEVELS = {"L2", "L3"}

MEMORY_TYPE_LABELS = {
    "correction": "纠错提示",
    "goal": "目标记忆",
    "preference": "偏好记忆",
    "profile": "画像记忆",
    "session_summary": "会话摘要",
    "support_strategy": "支持方式",
    "recurring_trigger": "触发线索",
    "relationship": "关系线索",
    "state": "状态线索",
    "safety_summary": "安全摘要",
}


def _compact_text(value: object, *, limit: int = MAX_ITEM_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _iter_values(value: object) -> Iterable[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _append_unique(items: list[str], value: object, *, limit: int = MAX_LIST_ITEMS) -> None:
    if len(items) >= limit:
        return
    for raw_item in _iter_values(value):
        item = _compact_text(raw_item)
        if not item or item in items:
            continue
        items.append(item)
        if len(items) >= limit:
            break


def _first_text(*values: object, limit: int = 120) -> str:
    for value in values:
        text = _compact_text(value, limit=limit)
        if text:
            return text
    return ""


def _digest_text(session_digest: dict[str, Any], key: str) -> object:
    return session_digest.get(key) if isinstance(session_digest, dict) else None


def _memory_hint(memory: dict[str, Any]) -> str:
    memory_type = str(memory.get("memory_type") or "session_summary")
    label = MEMORY_TYPE_LABELS.get(memory_type, "记忆")
    content = _first_text(memory.get("summary"), memory.get("content"), limit=120)
    return f"{label}：{content}" if content else ""


def _ordinary_memory_hints(retrieved_memories: list[dict[str, Any]] | None) -> list[str]:
    hints: list[str] = []
    for memory in retrieved_memories or []:
        if not isinstance(memory, dict):
            continue
        hint = _memory_hint(memory)
        if hint:
            _append_unique(hints, hint)
    return hints


def _safety_memory_hints(retrieved_memories: list[dict[str, Any]] | None) -> list[str]:
    hints: list[str] = []
    for memory in retrieved_memories or []:
        if not isinstance(memory, dict):
            continue
        if memory.get("memory_type") != "safety_summary" and memory.get("visibility") != "internal_safety":
            continue
        hint = _memory_hint(memory)
        if hint:
            _append_unique(hints, hint)
    return hints


def _correction_hints(
    user_profile_digest: dict[str, Any],
    retrieved_memories: list[dict[str, Any]] | None,
) -> list[str]:
    hints: list[str] = []
    _append_unique(hints, user_profile_digest.get("correction_hints"))
    for memory in retrieved_memories or []:
        if not isinstance(memory, dict) or memory.get("memory_type") != "correction":
            continue
        _append_unique(hints, _first_text(memory.get("summary"), memory.get("content")))
    return hints


def _profile_hints(user_profile_digest: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for key in ("usage_goals", "communication_preferences", "profile_hints", "preference_hints"):
        _append_unique(hints, user_profile_digest.get(key))
        if len(hints) >= MAX_LIST_ITEMS:
            break
    return hints


def _open_threads(session_digest: dict[str, Any], goal_state: dict[str, Any]) -> list[str]:
    threads: list[str] = []
    for key in ("open_threads", "goal_hints"):
        _append_unique(threads, goal_state.get(key))
    for key in ("unresolved_threads", "significant_changes"):
        _append_unique(threads, _digest_text(session_digest, key))
    return threads


def _conversation_focus(session_digest: dict[str, Any]) -> str:
    summary = _compact_text(_digest_text(session_digest, "summary_200chars"), limit=160)
    themes: list[str] = []
    _append_unique(themes, _digest_text(session_digest, "key_themes"), limit=3)
    if summary and themes:
        return f"{summary} 主题：{'、'.join(themes)}"
    if summary:
        return summary
    if themes:
        return f"主题：{'、'.join(themes)}"
    return ""


def _priority_notes(pack: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if pack.get("active_goal"):
        notes.append("优先围绕当前目标和澄清答案回应")
    if pack.get("style_corrections"):
        notes.append("纠错提示优先于旧偏好")
    if pack.get("conversation_focus"):
        notes.append("保持会话连续性，但不要直接复述摘要")
    if pack.get("retrieved_memory_hints"):
        notes.append("检索记忆只用于理解语境和节奏")
    return notes[:MAX_LIST_ITEMS]


def build_user_context_pack(
    *,
    current_text: str = "",
    risk_level: str = "L0",
    session_digest: dict[str, Any] | None = None,
    user_profile_digest: dict[str, Any] | None = None,
    goal_state: dict[str, Any] | None = None,
    retrieved_memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    session_digest = session_digest if isinstance(session_digest, dict) else {}
    user_profile_digest = user_profile_digest if isinstance(user_profile_digest, dict) else {}
    goal_state = goal_state if isinstance(goal_state, dict) else {}
    risk_level = str(risk_level or "L0")

    if risk_level in HIGH_RISK_LEVELS:
        pack = {
            "schema_version": SCHEMA_VERSION,
            "active_goal": "",
            "conversation_focus": "高风险场景：只保留安全连续性和当前安全处理。",
            "style_corrections": [],
            "profile_hints": [],
            "open_threads": [],
            "retrieved_memory_hints": _safety_memory_hints(retrieved_memories),
            "priority_notes": ["安全处理优先于普通上下文"],
        }
        return pack

    active_goal = _first_text(
        goal_state.get("current_goal"),
        goal_state.get("clarification_answer"),
        current_text if any(term in str(current_text) for term in ("我想", "目标", "理清", "解决")) else "",
        limit=120,
    )
    pack = {
        "schema_version": SCHEMA_VERSION,
        "active_goal": active_goal,
        "conversation_focus": _conversation_focus(session_digest),
        "style_corrections": _correction_hints(user_profile_digest, retrieved_memories),
        "profile_hints": _profile_hints(user_profile_digest),
        "open_threads": _open_threads(session_digest, goal_state),
        "retrieved_memory_hints": _ordinary_memory_hints(retrieved_memories),
        "priority_notes": [],
    }
    pack["priority_notes"] = _priority_notes(pack)
    return pack
