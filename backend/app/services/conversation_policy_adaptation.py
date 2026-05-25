from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.conversation_policy_anchors import has_any


ANALYSIS_BOUNDARY_TERMS = (
    "别又开始分析我",
    "别分析我",
    "别分析",
    "不要分析我",
    "不要分析",
    "别心理分析",
    "不要心理分析",
    "别心理化",
    "不要心理化",
)
QUESTION_BOUNDARY_TERMS = (
    "别一直问",
    "不要一直问",
    "别老问",
    "不要老问",
    "别追问",
    "不要追问",
    "问题太多",
)
SAFETY_BOUNDARY_TERMS = ("别问安全", "别一直问安全", "别盘问安全", "不要问安全")
PAUSE_REQUEST_TERMS = ("就停在这儿", "就停在这里", "停在这儿吧", "停在这里吧", "先停在这", "到这儿吧", "到这里吧")
ADAPTATION_COUNT_KEYS = (
    "avoid_analysis_turns",
    "avoid_questions_turns",
    "avoid_safety_check_turns",
    "prefer_direct_anchor_response_turns",
)
NEGATIVE_EXPLICIT_FEEDBACK = {"missed", "too_analytic", "too_generic", "too_many_questions"}


def correction_type(text: str) -> str:
    compact = "".join(text.split())
    if not compact:
        return "none"
    if has_any(compact, ("别一直问安全", "别问安全", "别盘问安全", "别继续盘问", "不想聊安全")):
        return "too_safety_focused"
    if "安全" in compact and has_any(compact, ("别问", "不要问", "别一直问", "不要一直问", "别老问", "别追问", "盘问")):
        return "too_safety_focused"
    if has_any(compact, ("心理分析", "心理化", "别分析", "不要分析", "别心理", "不是要你分析")):
        return "too_psychological"
    if has_any(compact, ("别一直问", "不要一直问", "别老问", "问题太多", "别追问")):
        return "too_many_questions"
    if has_any(compact, ("太像ai", "像ai", "像机器", "像客服", "机器人", "机器了")):
        return "too_ai_like"
    if has_any(compact, ("不是这个意思", "你理解错", "跑偏了", "不是这个")):
        return "not_that_meaning"
    return "none"


def matched_terms(text: str, terms: Sequence[str]) -> list[str]:
    compact = "".join(text.split())
    result: list[str] = []
    for term in terms:
        if not term or term not in compact or any(term in existing for existing in result):
            continue
        result = [existing for existing in result if existing not in term]
        result.append(term)
    return result


def is_pause_request(text: str) -> bool:
    return bool(matched_terms(text, PAUSE_REQUEST_TERMS))


def wants_to_keep_anchor_light(text: str) -> bool:
    compact = "".join(text.split())
    return (
        ("不是想聊" in compact or "不想聊" in compact or "不是要聊" in compact)
        and ("本身" in compact or "作品" in compact or "情节" in compact)
    )


def latest_assistant_policy(messages: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping):
            policy = metadata.get("conversation_move_policy")
            if isinstance(policy, Mapping):
                return policy
        policy = message.get("conversation_move_policy")
        if isinstance(policy, Mapping):
            return policy
    return {}


def quality_user_signal(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    quality_trace = payload.get("conversation_quality_trace")
    if isinstance(quality_trace, Mapping):
        user_signal = quality_trace.get("user_signal")
        if isinstance(user_signal, Mapping):
            return user_signal
    trace_summary = payload.get("trace_summary")
    if isinstance(trace_summary, Mapping):
        conversation_quality = trace_summary.get("conversation_quality")
        if isinstance(conversation_quality, Mapping):
            user_signal = conversation_quality.get("user_signal")
            if isinstance(user_signal, Mapping):
                return user_signal
    return {}


def latest_assistant_explicit_feedback(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        candidates: list[object] = [message]
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.insert(0, metadata)
        for candidate in candidates:
            feedback = str(quality_user_signal(candidate).get("explicit_feedback") or "").strip()
            if feedback:
                return feedback
    return "none"


def nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def adaptation_state_from_recent(
    messages: Sequence[Mapping[str, Any]],
    correction_type: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous_policy = latest_assistant_policy(messages)
    explicit_feedback = latest_assistant_explicit_feedback(messages)
    previous_raw = previous_policy.get("adaptation_state") if isinstance(previous_policy, Mapping) else None
    previous = previous_raw if isinstance(previous_raw, Mapping) else {}
    decayed: dict[str, Any] = {
        key: max(0, nonnegative_int(previous.get(key)) - 1)
        for key in ADAPTATION_COUNT_KEYS
    }
    decayed["last_correction_type"] = str(previous.get("last_correction_type") or "none")

    notes: list[str] = []
    source = "recent_assistant_metadata" if previous else "none"
    if decayed["avoid_questions_turns"] > 0:
        notes.append("减少问句")
    if decayed["avoid_analysis_turns"] > 0:
        notes.append("降低分析深度")
    if decayed["avoid_safety_check_turns"] > 0:
        notes.append("减少安全盘问")
    if decayed["prefer_direct_anchor_response_turns"] > 0:
        notes.append("优先直接回应用户线索")

    if explicit_feedback in NEGATIVE_EXPLICIT_FEEDBACK:
        source = "explicit_feedback" if source == "none" else f"{source}+explicit_feedback"
        decayed["last_correction_type"] = f"feedback_{explicit_feedback}"
        if explicit_feedback == "too_analytic":
            decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 3)
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                2,
            )
            notes.extend(["根据用户反馈降低分析深度", "优先直接回应用户线索"])
        elif explicit_feedback == "too_many_questions":
            decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 3)
            notes.append("根据用户反馈减少问句")
        elif explicit_feedback == "too_generic":
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                2,
            )
            notes.append("根据用户反馈更具体地接住本轮线索")
        elif explicit_feedback == "missed":
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                3,
            )
            decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 1)
            notes.extend(["根据用户反馈重新选择主线", "优先直接回应用户线索"])

    if correction_type == "too_psychological":
        decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 3)
        decayed["prefer_direct_anchor_response_turns"] = max(decayed["prefer_direct_anchor_response_turns"], 3)
        decayed["last_correction_type"] = correction_type
        notes.extend(["降低分析深度", "优先直接回应用户线索"])
    elif correction_type == "too_many_questions":
        decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 3)
        decayed["last_correction_type"] = correction_type
        notes.append("减少问句")
    elif correction_type == "too_safety_focused":
        decayed["avoid_safety_check_turns"] = max(decayed["avoid_safety_check_turns"], 2)
        decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 1)
        decayed["last_correction_type"] = correction_type
        notes.extend(["减少安全盘问", "减少问句"])
    elif correction_type == "not_that_meaning":
        decayed["prefer_direct_anchor_response_turns"] = max(decayed["prefer_direct_anchor_response_turns"], 3)
        decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 1)
        decayed["last_correction_type"] = correction_type
        notes.extend(["重新选择主线", "降低分析深度"])

    compact = "".join(text.split())
    if (
        has_any(compact, ("可以分析", "帮我分析", "分析一下", "展开分析"))
        and not matched_terms(compact, ANALYSIS_BOUNDARY_TERMS)
    ):
        decayed["avoid_analysis_turns"] = 0
        notes.append("用户允许本轮分析")

    deduped_notes = list(dict.fromkeys(note for note in notes if note))
    delta = {
        "source": source,
        "applied_correction": correction_type if correction_type != "none" else "none",
        "notes": "；".join(deduped_notes),
    }
    return decayed, delta
