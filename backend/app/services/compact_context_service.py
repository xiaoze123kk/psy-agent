from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = 1
SOURCE = "runtime_compact_context"
DEFAULT_MAX_CHARS = 6000
DEFAULT_MAX_MESSAGES = 10
TIMEZONE_NAME = "Asia/Wuhan"
HIGH_RISK_LEVELS = {"L2", "L3"}
COMPACT_MEMORY_CONFIRMATION_TERMS = (
    "明确",
    "以后",
    "希望",
    "不喜欢",
    "更希望",
    "记住",
    "每次",
    "总是",
    "先听",
    "少一点",
)
COMPACT_MEMORY_SENSITIVE_TERMS = (
    "诊断",
    "确诊",
    "抑郁症",
    "双相",
    "人格障碍",
    "ptsd",
    "用药",
    "处方",
    "自杀",
    "自伤",
    "结束生命",
    "具体工具",
    "风险等级",
)
QUALITY_NEGATIVE_FEEDBACK = {"missed", "too_analytic", "too_generic", "too_many_questions"}
QUALITY_OVER_QUESTIONING_REASONS = {"too_many_questions", "question_overload", "over_questioning"}
QUALITY_REPETITION_REASONS = {"repetitive", "repetition", "fixed_opening", "too_generic"}
QUALITY_TOPIC_DRIFT_REASONS = {"missed_primary_lane", "topic_drift", "off_topic"}
QUALITY_CONTEXT_BREAK_REASONS = {"context_break", "lost_context", "missed_current_turn", "missed_context"}
QUALITY_STALE_ANCHOR_REASONS = {"stale_anchor_misuse", "revived_stale_anchor", "stale_anchor"}
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
    over_questioning = quality_signals.get("recent_over_questioning_risk")
    if over_questioning in QUALITY_WARNING_VALUES:
        reasons.append("quality_over_questioning_risk")
    drift = quality_signals.get("topic_drift_risk")
    if drift in QUALITY_WARNING_VALUES:
        reasons.append("quality_topic_drift_risk")
    stale_anchor = quality_signals.get("stale_anchor_misuse_risk")
    if stale_anchor in QUALITY_WARNING_VALUES:
        reasons.append("quality_stale_anchor_misuse_risk")
    context_break = quality_signals.get("context_break_risk")
    if context_break in QUALITY_WARNING_VALUES:
        reasons.append("quality_context_break_risk")
    if str(quality_signals.get("user_correction_signal") or "") == "corrected":
        reasons.append("quality_user_correction_signal")
    return reasons


def _message_metadata(message: object) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {}
    metadata = message.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _quality_trace_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    quality_trace = metadata.get("conversation_quality_trace")
    if isinstance(quality_trace, dict):
        return quality_trace

    trace_summary = metadata.get("trace_summary")
    if isinstance(trace_summary, dict):
        conversation_quality = trace_summary.get("conversation_quality")
        if isinstance(conversation_quality, dict):
            return conversation_quality
    return {}


def _quality_reason_set(trace: dict[str, Any]) -> set[str]:
    validator = trace.get("validator_snapshot")
    if not isinstance(validator, dict):
        return set()

    reasons: set[str] = set()
    for key in ("validator_reasons", "experience_reasons"):
        values = validator.get(key)
        if not isinstance(values, list):
            continue
        reasons.update(str(value) for value in values if str(value or "").strip())
    severity = str(validator.get("severity") or "")
    if severity and severity not in {"passed", "unknown"}:
        reasons.add(severity)
    return reasons


def _quality_user_signal(trace: dict[str, Any]) -> dict[str, str]:
    signal = trace.get("user_signal")
    if not isinstance(signal, dict):
        return {}
    return {
        "explicit_feedback": str(signal.get("explicit_feedback") or "none"),
        "next_turn_signal": str(signal.get("next_turn_signal") or "unknown"),
    }


def _quality_question_count(trace: dict[str, Any]) -> int:
    shape = trace.get("turn_shape")
    if not isinstance(shape, dict):
        return 0
    count = shape.get("question_count")
    return count if isinstance(count, int) else 0


def _message_policy(metadata: dict[str, Any]) -> dict[str, Any]:
    policy = metadata.get("conversation_move_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _has_suppressed_anchor(policy: dict[str, Any]) -> bool:
    suppressed = policy.get("suppressed_recent_anchors")
    if isinstance(suppressed, list) and suppressed:
        return True
    handling = str(policy.get("stale_anchor_handling") or "")
    return bool(handling)


def quality_signals_from_recent_messages(recent_messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recent quality traces into compact-safe signal labels."""

    traces_seen = 0
    reason_labels: set[str] = set()
    over_questioning = False
    repetition = False
    topic_drift = False
    stale_anchor = False
    context_break = False
    user_corrected = False

    for message in recent_messages or []:
        metadata = _message_metadata(message)
        trace = _quality_trace_from_metadata(metadata)
        policy = _message_policy(metadata)
        if not trace and not policy:
            continue

        traces_seen += 1
        reasons = _quality_reason_set(trace)
        reason_labels.update(sorted(reasons))
        user_signal = _quality_user_signal(trace)
        feedback = user_signal.get("explicit_feedback", "none")
        next_turn_signal = user_signal.get("next_turn_signal", "unknown")

        if _quality_question_count(trace) >= 2 or reasons.intersection(QUALITY_OVER_QUESTIONING_REASONS):
            over_questioning = True
        if reasons.intersection(QUALITY_REPETITION_REASONS):
            repetition = True
        if reasons.intersection(QUALITY_TOPIC_DRIFT_REASONS):
            topic_drift = True
        if reasons.intersection(QUALITY_CONTEXT_BREAK_REASONS):
            context_break = True
        if reasons.intersection(QUALITY_STALE_ANCHOR_REASONS):
            stale_anchor = True
        if next_turn_signal == "corrected" or feedback in QUALITY_NEGATIVE_FEEDBACK:
            user_corrected = True
        if _has_suppressed_anchor(policy) and user_corrected:
            stale_anchor = True

    signals: dict[str, Any] = {}
    if over_questioning:
        signals["recent_over_questioning_risk"] = "high"
    if repetition:
        signals["recent_repetition_risk"] = "high"
    if topic_drift:
        signals["topic_drift_risk"] = "high"
    if stale_anchor:
        signals["stale_anchor_misuse_risk"] = "high"
    if context_break:
        signals["context_break_risk"] = "high"
    if user_corrected:
        signals["user_correction_signal"] = "corrected"

    known_issue_reasons = (
        QUALITY_OVER_QUESTIONING_REASONS
        | QUALITY_REPETITION_REASONS
        | QUALITY_TOPIC_DRIFT_REASONS
        | QUALITY_CONTEXT_BREAK_REASONS
        | QUALITY_STALE_ANCHOR_REASONS
    )
    issue_reasons = [
        reason
        for reason in sorted(reason_labels)
        if reason and reason not in {"passed", "unknown"} and reason in known_issue_reasons
    ]
    if issue_reasons:
        signals["last_quality_issue"] = ";".join(issue_reasons[:4])
    elif user_corrected:
        signals["last_quality_issue"] = "user_corrected_previous_turn"
    if traces_seen:
        signals["quality_trace_turns"] = traces_seen
    return signals


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
    if not quality_signals:
        quality_signals = quality_signals_from_recent_messages(recent_messages or [])
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


def _compact_memory_source_texts(compact_state: dict[str, Any]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for field in ("user_boundaries", "interaction_preferences"):
        values = compact_state.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            text = _compact_text(value, limit=160)
            if text:
                texts.append((field, text))
    return texts


def _is_explicit_compact_memory_candidate(text: str) -> bool:
    return any(term in text for term in COMPACT_MEMORY_CONFIRMATION_TERMS)


def _compact_memory_sensitive_reason(text: str) -> str:
    lowered = text.lower()
    for term in COMPACT_MEMORY_SENSITIVE_TERMS:
        if term.lower() in lowered:
            return f"sensitive_term:{term}"
    return ""


def _compact_memory_candidate(text: str, *, source_field: str) -> dict[str, Any]:
    content = f"用户明确表达了陪伴偏好：{text}"
    audit = {
        "source": "compact_state",
        "origin_field": source_field,
        "stability": "explicit_user_preference",
        "user_confirmation": "explicit",
        "ethical_boundary": "passed",
        "write_policy": "candidate_only_requires_review",
    }
    return {
        "memory_type": "preference",
        "title": "陪伴偏好候选",
        "summary": _compact_text(content, limit=180),
        "content": _compact_text(content, limit=260),
        "importance": 4,
        "visibility": "user_visible",
        "tags": ["支持方式", "compact候选"],
        "source": "compact_context",
        "review_state": "candidate_review",
        "structured_value": {
            "compact_memory_audit": audit,
        },
    }


def compact_memory_candidates_from_state(
    compact_state: dict[str, Any],
    *,
    risk_level: str = "L0",
    limit: int = 4,
) -> list[dict[str, Any]]:
    if not isinstance(compact_state, dict) or str(risk_level or "L0") in HIGH_RISK_LEVELS:
        return []

    candidates: list[dict[str, Any]] = []
    seen_contents: set[str] = set()
    for source_field, text in _compact_memory_source_texts(compact_state):
        if len(candidates) >= limit:
            break
        if not _is_explicit_compact_memory_candidate(text):
            continue
        if _compact_memory_sensitive_reason(text):
            continue
        candidate = _compact_memory_candidate(text, source_field=source_field)
        content = candidate["content"]
        if content in seen_contents:
            continue
        seen_contents.add(content)
        candidates.append(candidate)
    return candidates


def _safe_quality_signals(quality_signals: dict[str, Any], *, risk_level: str) -> dict[str, Any]:
    if risk_level in HIGH_RISK_LEVELS:
        return {"risk_continuity": "high_risk_details_filtered"}
    allowed_keys = {
        "recent_repetition_risk",
        "topic_drift_risk",
        "recent_over_questioning_risk",
        "stale_anchor_misuse_risk",
        "context_break_risk",
        "user_correction_signal",
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
    provided_quality_signals = quality_signals if isinstance(quality_signals, dict) else {}
    derived_quality_signals = quality_signals_from_recent_messages(messages)
    quality_signals = {**derived_quality_signals, **provided_quality_signals}
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
    memory_candidates = compact_memory_candidates_from_state(state, risk_level=risk_level)

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
        "memory_candidates": memory_candidates,
    }
