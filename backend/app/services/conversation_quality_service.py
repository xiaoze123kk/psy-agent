from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import ConversationTurn


QUESTION_MARKS = ("\uff1f", "?")
REGENERATION_AUDIT_TAGS = {
    "validator_regenerated",
    "empty_reply_regenerated",
    "empty_safety_regenerated",
    "validator_regeneration_exhausted",
}
PAUSE_TERMS = (
    "先停",
    "停在这里",
    "放在这里",
    "不用急",
    "不急着",
    "慢一点",
)
SAFETY_TERMS = ("安全", "危险", "伤害自己", "身边有人")
VALIDATION_OPENINGS = ("听起来", "我听见", "我听到", "我理解", "我能理解")
CORRECTION_SIGNAL_TERMS = (
    "不是这个意思",
    "你理解错",
    "理解错了",
    "跑偏",
    "别分析",
    "不要分析",
    "太分析",
    "别一直问",
    "问题太多",
    "没接住",
)
STOP_SIGNAL_TERMS = (
    "就先这样",
    "先这样",
    "停在这里",
    "停在这儿",
    "就停在这里",
    "就停在这儿",
    "不聊了",
    "晚点再说",
    "算了",
)
CONTINUE_SIGNAL_TERMS = (
    "继续",
    "接着",
    "说下去",
    "往下说",
    "嗯",
    "对",
    "是的",
    "就是",
    "然后",
)
NEGATIVE_FEEDBACK_VALUES = {"missed", "too_analytic", "too_generic", "too_many_questions"}


def _question_count(text: str) -> int:
    return sum(text.count(mark) for mark in QUESTION_MARKS)


def _length_bucket(text: str) -> str:
    compact = "".join(text.split())
    if len(compact) <= 80:
        return "short"
    if len(compact) <= 220:
        return "medium"
    return "long"


def _opening_pattern(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "unknown"
    if any(stripped.startswith(term) for term in SAFETY_TERMS):
        return "safety_check"
    if any(stripped.startswith(opening) for opening in VALIDATION_OPENINGS):
        return "validation_preface"
    if re.match(r"^《[^》]{1,32}》", stripped):
        return "anchor_echo"
    return "direct"


def _closing_pattern(text: str, suggested_actions: list[str]) -> str:
    stripped = text.strip()
    if not stripped:
        return "none"
    tail = stripped[-48:]
    if any(term in tail for term in PAUSE_TERMS):
        return "pause"
    if any(term in tail for term in SAFETY_TERMS):
        return "safety_micro_step"
    if stripped.endswith(QUESTION_MARKS):
        return "invitation"
    if suggested_actions:
        return "action_button"
    return "none"


def _topic_anchor_type(policy: dict[str, Any]) -> str:
    anchor = policy.get("topic_anchor")
    if isinstance(anchor, dict):
        value = anchor.get("type") or anchor.get("anchor_type") or anchor.get("kind") or "none"
        return str(value or "none")
    value = str(anchor or policy.get("topic_anchor_type") or "none").strip()
    if "/" in value:
        return value.split("/", 1)[0] or "none"
    return value or "none"


def _voice_mode(policy: dict[str, Any]) -> str:
    contract = policy.get("ningyu_voice_contract")
    if isinstance(contract, dict):
        voice = str(contract.get("voice_mode") or "").strip()
        if voice:
            return voice
    return str(policy.get("voice_mode") or "").strip()


def _cultural_response_mode(policy: dict[str, Any]) -> str:
    evidence = policy.get("anchor_evidence")
    if isinstance(evidence, dict):
        mode = str(evidence.get("response_mode") or "").strip()
        if mode:
            return mode
    return str(policy.get("cultural_response_mode") or "").strip()


def _lane_summary(policy: dict[str, Any]) -> dict[str, object]:
    lanes = policy.get("intent_lanes")
    if not isinstance(lanes, list):
        return {}

    primary_lane = str(policy.get("primary_lane") or "").strip()
    primary_kind = ""
    forbidden_count = 0
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        priority = str(lane.get("priority") or "").strip()
        kind = str(lane.get("kind") or "").strip()
        handling = str(lane.get("handling") or "").strip()
        if priority == "primary" and not primary_kind:
            primary_kind = kind
        if handling.startswith("do_not_") or priority == "blocking_style_constraint":
            forbidden_count += 1

    summary: dict[str, object] = {"intent_lane_count": len(lanes)}
    if primary_lane:
        summary["primary_lane"] = primary_lane
    if primary_kind:
        summary["primary_lane_kind"] = primary_kind
    if forbidden_count:
        summary["forbidden_lane_count"] = forbidden_count
    return summary


def _policy_snapshot(conversation_move_policy: dict[str, Any], risk_level: str) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "conversation_move": str(conversation_move_policy.get("conversation_move") or "unknown"),
        "risk_level": str(risk_level or conversation_move_policy.get("risk_level") or "L0"),
        "topic_anchor_type": _topic_anchor_type(conversation_move_policy),
    }
    cultural_response_mode = _cultural_response_mode(conversation_move_policy)
    if cultural_response_mode:
        snapshot["cultural_response_mode"] = cultural_response_mode
    voice_mode = _voice_mode(conversation_move_policy)
    if voice_mode:
        snapshot["voice_mode"] = voice_mode
    snapshot.update(_lane_summary(conversation_move_policy))
    return snapshot


def _regeneration_attempted(regeneration_attempted: bool, audit_tags: list[str] | None, severity: str) -> bool:
    tags = set(audit_tags or [])
    return bool(
        regeneration_attempted
        or tags.intersection(REGENERATION_AUDIT_TAGS)
        or severity == "repaired"
    )


def build_conversation_quality_trace(
    *,
    assistant_text: str,
    suggested_actions: list[str],
    conversation_move_policy: dict[str, Any],
    risk_level: str,
    validator_severity: str,
    validator_reasons: list[str],
    experience_validator_reasons: list[str],
    regeneration_attempted: bool,
    audit_tags: list[str] | None = None,
) -> dict[str, object]:
    """Build a privacy-preserving quality trace for one assistant turn."""

    text = str(assistant_text or "")
    actions = [str(action) for action in suggested_actions if str(action or "").strip()]
    severity = str(validator_severity or "passed")
    return {
        "turn_shape": {
            "assistant_length_bucket": _length_bucket(text),
            "question_count": _question_count(text),
            "opening_pattern": _opening_pattern(text),
            "closing_pattern": _closing_pattern(text, actions),
        },
        "policy_snapshot": _policy_snapshot(dict(conversation_move_policy or {}), str(risk_level or "L0")),
        "validator_snapshot": {
            "severity": severity,
            "validator_reasons": sorted({str(reason) for reason in validator_reasons if str(reason).strip()}),
            "experience_reasons": sorted(
                {str(reason) for reason in experience_validator_reasons if str(reason).strip()}
            ),
            "regeneration_attempted": _regeneration_attempted(
                regeneration_attempted,
                audit_tags,
                severity,
            ),
        },
        "user_signal": {
            "explicit_feedback": "none",
            "next_turn_signal": "unknown",
        },
    }


def infer_next_turn_signal(user_text: str) -> str:
    compact = "".join(str(user_text or "").split())
    if not compact:
        return "unknown"
    if any(term in compact for term in CORRECTION_SIGNAL_TERMS):
        return "corrected"
    if any(term in compact for term in STOP_SIGNAL_TERMS):
        return "stopped"
    if any(term in compact for term in CONTINUE_SIGNAL_TERMS):
        return "continued"
    return "unknown"


def _quality_trace_from_snapshot(snapshot: object) -> Mapping[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    quality_trace = snapshot.get("conversation_quality_trace")
    if isinstance(quality_trace, Mapping):
        return quality_trace
    trace_summary = snapshot.get("trace_summary")
    if isinstance(trace_summary, Mapping):
        conversation_quality = trace_summary.get("conversation_quality")
        if isinstance(conversation_quality, Mapping):
            return conversation_quality
    return {}


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def build_conversation_quality_summary(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None = None,
    limit: int = 200,
) -> dict[str, object]:
    bounded_limit = max(1, min(int(limit), 500))
    query = (
        select(ConversationTurn)
        .where(
            ConversationTurn.user_id == user_id,
            ConversationTurn.turn_status == "completed",
        )
        .order_by(desc(ConversationTurn.created_at))
        .limit(bounded_limit)
    )
    if thread_id:
        query = query.where(ConversationTurn.thread_id == thread_id)

    feedback_counts: Counter[str] = Counter()
    next_turn_signal_counts: Counter[str] = Counter()
    conversation_move_counts: Counter[str] = Counter()
    voice_mode_counts: Counter[str] = Counter()
    validator_severity_counts: Counter[str] = Counter()
    validator_reason_counts: Counter[str] = Counter()
    experience_reason_counts: Counter[str] = Counter()
    negative_feedback_by_move: Counter[str] = Counter()
    question_count_buckets: Counter[str] = Counter()

    total_turns = 0
    for turn in db.scalars(query):
        trace = _quality_trace_from_snapshot(turn.response_snapshot)
        if not trace:
            continue
        total_turns += 1
        user_signal = trace.get("user_signal") if isinstance(trace.get("user_signal"), Mapping) else {}
        policy_snapshot = trace.get("policy_snapshot") if isinstance(trace.get("policy_snapshot"), Mapping) else {}
        validator_snapshot = (
            trace.get("validator_snapshot") if isinstance(trace.get("validator_snapshot"), Mapping) else {}
        )
        turn_shape = trace.get("turn_shape") if isinstance(trace.get("turn_shape"), Mapping) else {}

        feedback = str(user_signal.get("explicit_feedback") or "none")
        next_turn_signal = str(user_signal.get("next_turn_signal") or "unknown")
        move = str(policy_snapshot.get("conversation_move") or "unknown")
        voice_mode = str(policy_snapshot.get("voice_mode") or "unknown")
        severity = str(validator_snapshot.get("severity") or "unknown")
        question_count = turn_shape.get("question_count")

        feedback_counts[feedback] += 1
        next_turn_signal_counts[next_turn_signal] += 1
        conversation_move_counts[move] += 1
        voice_mode_counts[voice_mode] += 1
        validator_severity_counts[severity] += 1
        if feedback in NEGATIVE_FEEDBACK_VALUES:
            negative_feedback_by_move[move] += 1

        if isinstance(question_count, int):
            if question_count <= 0:
                question_count_buckets["0"] += 1
            elif question_count == 1:
                question_count_buckets["1"] += 1
            else:
                question_count_buckets["2_plus"] += 1

        reasons = validator_snapshot.get("experience_reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                reason_key = str(reason or "").strip()
                if reason_key:
                    experience_reason_counts[reason_key] += 1
        validator_reasons = validator_snapshot.get("validator_reasons")
        if isinstance(validator_reasons, list):
            for reason in validator_reasons:
                reason_key = str(reason or "").strip()
                if reason_key:
                    validator_reason_counts[reason_key] += 1

    return {
        "total_turns": total_turns,
        "limit": bounded_limit,
        "thread_id": thread_id,
        "feedback_counts": _counter_dict(feedback_counts),
        "next_turn_signal_counts": _counter_dict(next_turn_signal_counts),
        "conversation_move_counts": _counter_dict(conversation_move_counts),
        "voice_mode_counts": _counter_dict(voice_mode_counts),
        "validator_severity_counts": _counter_dict(validator_severity_counts),
        "validator_reason_counts": _counter_dict(validator_reason_counts),
        "experience_reason_counts": _counter_dict(experience_reason_counts),
        "negative_feedback_by_move": _counter_dict(negative_feedback_by_move),
        "question_count_buckets": _counter_dict(question_count_buckets),
    }
