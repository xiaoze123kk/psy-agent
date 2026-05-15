from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}
SAFETY_CONTEXT_MEMORY_TYPES = {"safety_summary", "support_strategy", "preference", "correction", "relationship"}
SUPPORT_MEMORY_TYPES = {"relationship", "safety_summary"}
HIGH_RISK_DETAIL_TERMS = (
    "刀",
    "药",
    "跳楼",
    "楼顶",
    "绳",
    "煤气",
    "割腕",
    "安眠药",
    "pills",
    "knife",
    "roof",
    "bridge",
)


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _append_unique(items: list[str], value: object, *, limit: int = 5, item_limit: int = 120) -> None:
    text = _compact(value)
    if not text:
        return
    if len(text) > item_limit:
        text = text[:item_limit].rstrip()
    if text in items:
        return
    items.append(text)
    if len(items) > limit:
        del items[limit:]


def sanitize_safety_context_text(text: object, *, risk_level: str) -> str:
    sanitized = _compact(text)
    sanitized = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[已过滤联系方式]", sanitized)
    sanitized = re.sub(r"(?<!\d)\d[\d\s-]{6,}\d(?!\d)", "[已过滤联系方式]", sanitized)
    if risk_level in HIGH_RISK_LEVELS:
        for term in HIGH_RISK_DETAIL_TERMS:
            sanitized = re.sub(re.escape(term), "[已概括安全风险细节]", sanitized, flags=re.IGNORECASE)
    return sanitized


def _memory_text(memory: Mapping[str, Any], *, risk_level: str) -> str:
    value = memory.get("summary") or memory.get("description") or memory.get("content") or memory.get("title") or ""
    return sanitize_safety_context_text(value, risk_level=risk_level)


def build_safety_context_pack(
    *,
    risk_level: str,
    retrieved_memories: list[dict[str, Any]] | None,
    session_digest: Mapping[str, Any] | None,
    user_context_pack: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if risk_level not in HIGH_RISK_LEVELS:
        return {}

    memory_hints: list[str] = []
    support_hints: list[str] = []
    style_corrections: list[str] = []
    continuity_notes: list[str] = []

    for raw in retrieved_memories or []:
        if not isinstance(raw, Mapping):
            continue
        memory_type = str(raw.get("memory_type") or "")
        if memory_type not in SAFETY_CONTEXT_MEMORY_TYPES:
            continue
        text = _memory_text(raw, risk_level=risk_level)
        if not text:
            continue
        if memory_type in SUPPORT_MEMORY_TYPES:
            _append_unique(support_hints, text)
        else:
            _append_unique(memory_hints, text)

    if isinstance(user_context_pack, Mapping):
        for item in user_context_pack.get("style_corrections") or []:
            _append_unique(style_corrections, sanitize_safety_context_text(item, risk_level=risk_level))

    if isinstance(session_digest, Mapping):
        summary = sanitize_safety_context_text(session_digest.get("summary_200chars"), risk_level=risk_level)
        if summary:
            _append_unique(continuity_notes, summary)

    return {
        "schema_version": 1,
        "risk_level": risk_level,
        "memory_hints": memory_hints,
        "support_hints": support_hints,
        "style_corrections": style_corrections,
        "continuity_notes": continuity_notes,
    }
