from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = 1
SOURCE = "runtime_compact_context"
DEFAULT_MAX_CHARS = 6000
DEFAULT_MAX_MESSAGES = 10
TIMEZONE_NAME = "Asia/Wuhan"
HIGH_RISK_LEVELS = {"L2", "L3"}
QUALITY_WARNING_VALUES = {"high", "warn", "warning", "poor", "bad", True}
ANCHOR_TERMS = ("在轮下", "德米安", "荣格")
HIGH_RISK_SAFE_SUMMARY = "用户表达了安全相关痛苦或冲动；只保留安全连续性，不复述危险方法、地点、时间或数量。"


def _compact_text(value: object, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _message_content(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _message_role(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    return str(message.get("role") or "")


def _safe_text(value: object, *, risk_level: str, limit: int = 180) -> str:
    if risk_level in HIGH_RISK_LEVELS:
        return HIGH_RISK_SAFE_SUMMARY
    text = _compact_text(value, limit=limit)
    return text


def _append_unique(items: list[str], value: object, *, risk_level: str = "L0", limit: int = 5) -> None:
    if len(items) >= limit:
        return
    text = _safe_text(value, risk_level=risk_level)
    if text and text not in items:
        items.append(text)


def _quality_reasons(quality_signals: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    repetition = quality_signals.get("recent_repetition_risk")
    if repetition in QUALITY_WARNING_VALUES:
        reasons.append("quality_repetition_risk")
    drift = quality_signals.get("topic_drift_risk")
    if drift in QUALITY_WARNING_VALUES:
        reasons.append("quality_topic_drift_risk")
    return reasons


def estimate_context_budget(recent_messages: list[dict[str, Any]], max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    max_chars = max(1, int(max_chars or DEFAULT_MAX_CHARS))
    used_chars = sum(len(_message_content(message)) for message in recent_messages or [])
    return {
        "used_chars": used_chars,
        "max_chars": max_chars,
        "usage_ratio": used_chars / max_chars,
        "remaining_chars": max(0, max_chars - used_chars),
        "message_count": len(recent_messages or []),
    }


def should_compact_context(
    recent_messages: list[dict[str, Any]],
    quality_signals: dict[str, Any] | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
    force: bool = False,
) -> dict[str, Any]:
    quality_signals = quality_signals if isinstance(quality_signals, dict) else {}
    budget = estimate_context_budget(recent_messages or [], max_chars=max_chars)
    reasons: list[str] = []

    if force:
        reasons.append("force")
    if budget["message_count"] > int(max_messages or DEFAULT_MAX_MESSAGES):
        reasons.append("message_threshold")
    if budget["used_chars"] > budget["max_chars"]:
        reasons.append("character_threshold")
    reasons.extend(_quality_reasons(quality_signals))

    return {
        "should_compact": bool(reasons),
        "reasons": reasons,
        "budget": budget,
        "quality_signals": quality_signals,
    }


def _extract_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for match in re.findall(r"《[^》]{1,40}》", text or ""):
        if match not in anchors:
            anchors.append(match)
    for match in re.findall(r"[“\"']([^“”\"']{2,24})[”\"']", text or ""):
        if match not in anchors:
            anchors.append(match)
    for term in ANCHOR_TERMS:
        if term in text and term not in anchors and not any(term in anchor for anchor in anchors):
            anchors.append(term)
    return anchors


def _append_anchor_candidate(items: list[str], value: object) -> None:
    text = _compact_text(value, limit=60)
    if text and text not in items:
        items.append(text)


def _structured_anchor_candidates(session_digest: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    raw_stale_threads = session_digest.get("stale_threads")
    if isinstance(raw_stale_threads, list):
        for item in raw_stale_threads:
            if isinstance(item, dict):
                _append_anchor_candidate(candidates, item.get("topic") or item.get("anchor"))
            else:
                _append_anchor_candidate(candidates, item)

    raw_suppressed = session_digest.get("suppressed_recent_anchors")
    if isinstance(raw_suppressed, list):
        for item in raw_suppressed:
            _append_anchor_candidate(candidates, item)

    anchor_state = session_digest.get("anchor_state")
    if isinstance(anchor_state, dict):
        status = str(anchor_state.get("anchor_status") or anchor_state.get("status") or "")
        if status in {"stale", "suppressed", "inactive"}:
            _append_anchor_candidate(candidates, anchor_state.get("recent_anchor") or anchor_state.get("anchor"))

    return candidates


def _stale_threads(
    recent_messages: list[dict[str, Any]],
    session_digest: dict[str, Any],
    *,
    max_recent_messages: int,
) -> list[dict[str, str]]:
    recent_window = recent_messages[-max_recent_messages:] if max_recent_messages > 0 else []
    recent_user_text = " ".join(
        _message_content(message) for message in recent_window if _message_role(message) == "user"
    )
    older_text = " ".join(_message_content(message) for message in recent_messages[:-max_recent_messages])
    digest_text = " ".join(str(value or "") for value in session_digest.values())

    stale: list[dict[str, str]] = []
    candidates = [
        *_structured_anchor_candidates(session_digest),
        *_extract_anchors(f"{older_text} {digest_text}"),
    ]
    for anchor in candidates:
        if anchor in recent_user_text:
            continue
        if any(existing["topic"] == anchor for existing in stale):
            continue
        stale.append(
            {
                "topic": anchor,
                "reuse_policy": "除非用户主动重新提起，否则不要复用这个旧锚点。",
            }
        )
    return stale[:5]


def _user_boundaries(messages: list[dict[str, Any]], *, risk_level: str) -> tuple[list[str], list[str]]:
    if risk_level in HIGH_RISK_LEVELS:
        return ["安全场景下使用低压、短句、具体的稳定支持。"], ["不要复述危险细节，不连续追问。"]

    boundaries: list[str] = []
    preferences: list[str] = []
    for message in messages:
        if _message_role(message) != "user":
            continue
        text = _message_content(message)
        if any(term in text for term in ("不要", "别", "不想")):
            if any(term in text for term in ("问", "追问", "连着问")):
                _append_unique(preferences, text, risk_level=risk_level)
            if any(term in text for term in ("分析", "评价", "判断", "建议")):
                _append_unique(boundaries, text, risk_level=risk_level)
            elif not any(term in text for term in ("问", "追问", "连着问")):
                _append_unique(boundaries, text, risk_level=risk_level)
    return boundaries, preferences


def _active_threads(messages: list[dict[str, Any]], *, risk_level: str) -> list[dict[str, str]]:
    if risk_level in HIGH_RISK_LEVELS:
        return [{"topic": "安全连续性", "next_move_hint": "先稳定当下，不复述危险细节。"}]

    threads: list[dict[str, str]] = []
    for message in reversed(messages):
        if _message_role(message) != "user":
            continue
        text = _safe_text(_message_content(message), risk_level=risk_level, limit=80)
        if not text:
            continue
        threads.append({"topic": text, "next_move_hint": "先承接当前表达，再谨慎推进。"})
        if len(threads) >= 3:
            break
    return list(reversed(threads))


def _summary(
    messages: list[dict[str, Any]],
    session_digest: dict[str, Any],
    *,
    risk_level: str,
) -> str:
    if risk_level in HIGH_RISK_LEVELS:
        return HIGH_RISK_SAFE_SUMMARY

    digest_summary = session_digest.get("summary_200chars") if isinstance(session_digest, dict) else ""
    if digest_summary:
        return _safe_text(digest_summary, risk_level=risk_level, limit=220)
    user_messages = [_message_content(message) for message in messages if _message_role(message) == "user"]
    if not user_messages:
        return ""
    return _safe_text(" / ".join(user_messages[-3:]), risk_level=risk_level, limit=220)


def _time_policy() -> dict[str, str]:
    return {
        "timezone": TIMEZONE_NAME,
        "source": "runtime",
        "use_policy": "每轮由运行时注入当前时间；compact 只保留时区和自然使用原则。",
    }


def _message_id(message: dict[str, Any], index: int) -> str:
    return str(message.get("id") or message.get("turn_id") or f"message_{index}")


def _compact_range(messages: list[dict[str, Any]], *, max_recent_messages: int) -> dict[str, list[str] | str]:
    forgotten = messages[:-max_recent_messages] if max_recent_messages > 0 else messages
    kept_tail = messages[-max_recent_messages:] if max_recent_messages > 0 else []
    forgotten_ids = [_message_id(message, index) for index, message in enumerate(forgotten)]
    kept_tail_ids = [
        _message_id(message, len(forgotten) + index)
        for index, message in enumerate(kept_tail)
    ]
    return {
        "forgotten_turn_ids": forgotten_ids,
        "summary_offset_turn_id": forgotten_ids[0] if forgotten_ids else "",
        "kept_head_turn_ids": [],
        "kept_tail_turn_ids": kept_tail_ids,
    }


def _safe_quality_signals(quality_signals: dict[str, Any], *, risk_level: str) -> dict[str, Any]:
    if risk_level in HIGH_RISK_LEVELS:
        return {"risk_continuity": "high_risk_details_filtered"}
    allowed_keys = {
        "recent_repetition_risk",
        "topic_drift_risk",
        "recent_over_questioning_risk",
        "last_quality_issue",
    }
    safe: dict[str, Any] = {}
    for key, value in quality_signals.items():
        if key not in allowed_keys:
            continue
        safe[key] = _compact_text(value, limit=120)
    return safe


def build_compact_context_pack(
    recent_messages: list[dict[str, Any]],
    session_digest: dict[str, Any] | None = None,
    risk_level: str = "L0",
    quality_signals: dict[str, Any] | None = None,
    max_recent_messages: int = DEFAULT_MAX_MESSAGES,
    created_at: str = "",
) -> dict[str, Any]:
    messages = recent_messages or []
    session_digest = session_digest if isinstance(session_digest, dict) else {}
    quality_signals = quality_signals if isinstance(quality_signals, dict) else {}
    risk_level = str(risk_level or "L0")
    max_recent_messages = max(1, int(max_recent_messages or DEFAULT_MAX_MESSAGES))
    summary = _summary(messages, session_digest, risk_level=risk_level)
    boundaries, preferences = _user_boundaries(messages, risk_level=risk_level)
    stale_threads = [] if risk_level in HIGH_RISK_LEVELS else _stale_threads(
        messages,
        session_digest,
        max_recent_messages=max_recent_messages,
    )
    safe_quality_signals = _safe_quality_signals(quality_signals, risk_level=risk_level)
    decision = should_compact_context(
        messages,
        quality_signals=safe_quality_signals,
        max_messages=max_recent_messages,
        force=risk_level in HIGH_RISK_LEVELS,
    )

    safety_note = "安全连续性优先；仅保留低刺激概括，避免复述危险操作细节。"
    if risk_level not in HIGH_RISK_LEVELS:
        safety_note = "按当前风险等级保持普通支持性回应。"

    state = {
        "summary_for_prompt": summary,
        "active_threads": _active_threads(messages[-max_recent_messages:], risk_level=risk_level),
        "stale_threads": stale_threads,
        "user_boundaries": boundaries,
        "interaction_preferences": preferences,
        "safety_context": {
            "risk_level": risk_level,
            "note": safety_note,
        },
        "time_context_policy": _time_policy(),
        "quality_signals": safe_quality_signals,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "event": {
            "type": "compact_event",
            "schema_version": SCHEMA_VERSION,
            "trigger": {
                "reason": decision["reasons"],
                "usage_ratio": decision["budget"]["usage_ratio"],
                "message_count": decision["budget"]["message_count"],
            },
            "range": _compact_range(messages, max_recent_messages=max_recent_messages),
            "summary": summary,
            "quality_flags": {
                "summary_confidence": "medium" if summary else "low",
                "risk_signal_preserved": risk_level in HIGH_RISK_LEVELS,
                "stale_anchor_filtered": bool(stale_threads),
            },
            "created_at": str(created_at or ""),
        },
        "state": state,
        "memory_candidates": [],
    }
