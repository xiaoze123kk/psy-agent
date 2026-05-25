from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.conversation_policy_adaptation import (
    ADAPTATION_COUNT_KEYS,
    ANALYSIS_BOUNDARY_TERMS,
    NEGATIVE_EXPLICIT_FEEDBACK,
    PAUSE_REQUEST_TERMS,
    QUESTION_BOUNDARY_TERMS,
    SAFETY_BOUNDARY_TERMS,
    adaptation_state_from_recent as _adaptation_state_from_recent,
    correction_type as _correction_type,
    is_pause_request as _is_pause_request,
    latest_assistant_explicit_feedback as _latest_assistant_explicit_feedback,
    latest_assistant_policy as _latest_assistant_policy,
    matched_terms as _matched_terms,
    nonnegative_int as _nonnegative_int,
    quality_user_signal as _quality_user_signal,
    wants_to_keep_anchor_light as _wants_to_keep_anchor_light,
)
from app.services.conversation_policy_anchors import (
    COMMON_CULTURAL_ANCHORS,
    CULTURAL_ANCHOR_TYPES,
    DAILY_DETAIL_TERMS,
    DISTRESS_TERMS,
    GENERIC_PERSON_ANCHORS,
    HIGH_RISK_LEVELS,
    KNOWLEDGE_BOUNDARY_TERMS,
    LIGHT_CHAT_TERMS,
    LITERARY_CONTEXT_TERMS,
    MEDIA_TERMS,
    METAPHOR_TERMS,
    PHILOSOPHICAL_CONTEXT_TERMS,
    SELF_REFERENCE_TERMS,
    SHORT_FOLLOWUP_TERMS,
    THEME_CLUE_TERMS,
    anchor_clue as _anchor_clue,
    anchor_evidence as _anchor_evidence,
    anchor_value as _anchor_value,
    clean_person_candidate as _clean_person_candidate,
    common_cultural_anchor as _common_cultural_anchor,
    cultural_response_mode as _cultural_response_mode,
    dedupe_clues as _dedupe_clues,
    extract_book_title as _extract_book_title,
    has_any as _has_any,
    is_cultural_lane_anchor as _is_cultural_lane_anchor,
    is_short_followup as _is_short_followup,
    person_anchor_value as _person_anchor_value,
    recent_high_risk_seen as _recent_high_risk_seen,
    recent_messages as _recent_messages,
    recent_quoted_titles as _recent_quoted_titles,
    recent_title_mentioned as _recent_title_mentioned,
    suppressed_recent_anchors as _suppressed_recent_anchors,
    text_from_state as _text,
    topic_anchor_type as _topic_anchor_type,
    user_clues_for_anchor as _user_clues_for_anchor,
)
from app.services.conversation_policy_structure import (
    base_structure_mode as _base_structure_mode,
    recent_assistant_contents as _recent_assistant_contents,
    recent_assistant_opening_mode as _recent_assistant_opening_mode,
    recent_reused_structure as _recent_reused_structure,
    reply_structure_signature as _reply_structure_signature,
    structure_mode_for as _structure_mode_for,
    structure_style as _structure_style,
)


def _intent_lanes_for(
    text: str,
    anchor_type: str,
    anchor_value: str,
    correction_type: str,
) -> tuple[str, list[dict[str, Any]]]:
    lanes: list[dict[str, Any]] = []
    self_clues = _matched_terms(text, SELF_REFERENCE_TERMS)
    analysis_boundary_clues = _matched_terms(text, ANALYSIS_BOUNDARY_TERMS)
    question_boundary_clues = _matched_terms(text, QUESTION_BOUNDARY_TERMS)
    safety_boundary_clues = _matched_terms(text, SAFETY_BOUNDARY_TERMS)
    keep_anchor_light = _wants_to_keep_anchor_light(text)

    if _is_cultural_lane_anchor(anchor_type) and anchor_value:
        priority = "secondary" if self_clues or keep_anchor_light else "primary"
        handling = "do_not_expand_work_detail" if keep_anchor_light or self_clues else "respond_to_anchor"
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "cultural_anchor",
                "anchor_type": anchor_type,
                "anchor_value": anchor_value,
                "priority": priority,
                "handling": handling,
            }
        )

    if self_clues:
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "self_reference",
                "user_clues": self_clues,
                "priority": "primary",
                "handling": "respond_to_user_clue",
            }
        )

    if analysis_boundary_clues or correction_type == "too_psychological":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": analysis_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "lower_analysis_depth",
            }
        )
    if question_boundary_clues or correction_type == "too_many_questions":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": question_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "reduce_questions",
            }
        )
    if safety_boundary_clues or correction_type == "too_safety_focused":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": safety_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "avoid_safety_check",
            }
        )

    primary_lane = "quiet_presence" if _is_pause_request(text) else ""
    for lane in lanes:
        if lane.get("priority") == "primary":
            primary_lane = str(lane.get("kind") or primary_lane)
            break
    if not primary_lane:
        if correction_type != "none":
            primary_lane = "correction"
        elif lanes:
            primary_lane = str(lanes[0].get("kind") or "current_turn")
        else:
            primary_lane = "current_turn"
    return primary_lane, lanes


def _voice_contract_for(
    *,
    text: str,
    risk_level: str,
    conversation_move: str,
    correction_type: str,
    anchor_type: str,
    primary_lane: str,
    intent_lanes: Sequence[Mapping[str, Any]],
    adaptation_state: Mapping[str, Any],
) -> dict[str, Any]:
    has_blocking_boundary = any(
        str(lane.get("priority") or "") == "blocking_style_constraint" for lane in intent_lanes
    )
    if risk_level in HIGH_RISK_LEVELS:
        voice_mode = "safety_gentle"
    elif _is_pause_request(text):
        voice_mode = "quiet_presence"
    elif correction_type != "none":
        voice_mode = "correction_repair"
    elif primary_lane == "self_reference" or _is_cultural_lane_anchor(anchor_type):
        voice_mode = "anchored_companion"
    elif conversation_move == "ordinary_chat":
        voice_mode = "ordinary_chat"
    else:
        voice_mode = "quiet_presence" if len("".join(text.split())) <= 12 else "anchored_companion"

    analysis_depth = "light"
    if voice_mode in {"quiet_presence", "safety_gentle"}:
        analysis_depth = "none"
    elif voice_mode == "ordinary_chat":
        analysis_depth = "none"
    elif correction_type == "too_psychological" or adaptation_state.get("avoid_analysis_turns", 0) > 0:
        analysis_depth = "none"
    elif has_blocking_boundary:
        analysis_depth = "none"

    question_budget = 1
    if voice_mode == "quiet_presence" or has_blocking_boundary:
        question_budget = 0
    if adaptation_state.get("avoid_questions_turns", 0) > 0:
        question_budget = 0
    if correction_type in {"too_many_questions", "too_psychological"}:
        question_budget = 0
    if risk_level in HIGH_RISK_LEVELS:
        question_budget = 1

    sentence_budget = "2-4"
    if voice_mode == "quiet_presence":
        sentence_budget = "1-2"
    elif voice_mode == "safety_gentle":
        sentence_budget = "1-3"
    elif conversation_move == "ordinary_chat":
        sentence_budget = "1-3"

    opening_preference = "direct"
    if voice_mode in {"ordinary_chat", "quiet_presence", "correction_repair"}:
        opening_preference = "no_preface"
    elif primary_lane in {"self_reference", "cultural_anchor"}:
        opening_preference = "echo_user_words"

    closing_preference = "soft_invitation" if question_budget > 0 else "pause"
    if voice_mode == "safety_gentle":
        closing_preference = "micro_action"

    return {
        "voice_mode": voice_mode,
        "analysis_depth": analysis_depth,
        "question_budget": question_budget,
        "sentence_budget": sentence_budget,
        "opening_preference": opening_preference,
        "closing_preference": closing_preference,
        "humor_allowed": voice_mode == "ordinary_chat",
        "avoid_patterns": ["听起来你", "这说明你", "你可能是在"],
    }


def default_actions_for_conversation_move_policy(policy: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(policy, Mapping):
        return []
    button_style = str(policy.get("button_style") or "")
    move = str(policy.get("conversation_move") or "")
    topic_anchor = str(policy.get("topic_anchor") or "")
    anchor_value = str(policy.get("anchor_value") or "").strip("《》「」“” ")
    if button_style == "topic_continue":
        if anchor_value and topic_anchor == "philosophical":
            return [f"先聊{anchor_value}", f"{anchor_value}这点有意思", "沿着这个聊"]
        if anchor_value and topic_anchor in {"literary", "media", "metaphor"}:
            return [f"先停在{anchor_value}这里", "这个比喻很准", "沿着这个聊"]
        if anchor_value:
            return [f"先说{anchor_value}", f"{anchor_value}这点有意思", "沿着这个聊"]
        return ["这个比喻很准", "沿着这个聊", "先停在这句话上"]
    if button_style == "safety_micro_reply":
        return ["我还在", "先慢一点", "别继续盘问"]
    if button_style == "user_voice":
        if move == "correction_followup":
            if anchor_value:
                return [f"先聊{anchor_value}", "就按这个方向来", "换个说法"]
            return ["先别分析", "就按这个意思来", "换个说法"]
        if anchor_value and topic_anchor == "daily_detail":
            return [f"就聊这{anchor_value}", f"这{anchor_value}挺有意思", "随便聊两句"]
        if anchor_value:
            return [f"就聊{anchor_value}", f"{anchor_value}挺有意思", "随便聊两句"]
        return ["就随便聊聊", "这个挺有意思", "换个轻一点的"]
    return []


def build_conversation_move_policy(state: Mapping[str, Any]) -> dict[str, Any]:
    text = _text(state).strip()
    messages = _recent_messages(state)
    risk_level = str(state.get("risk_level") or "L0")
    risk_policy = state.get("risk_response_policy")
    risk_phase = str(risk_policy.get("risk_phase") if isinstance(risk_policy, Mapping) else state.get("risk_phase") or "")
    correction_type = _correction_type(text)
    anchor_type = _topic_anchor_type(text, messages)
    anchor_value = _anchor_value(text, anchor_type, messages)
    anchor_evidence = _anchor_evidence(text, anchor_type, anchor_value, messages)
    if anchor_type == "none" and anchor_evidence:
        anchor_type = str(anchor_evidence.get("anchor_type") or anchor_type)
    suppressed_recent_anchors = _suppressed_recent_anchors(text, anchor_type, anchor_value, messages)
    recent_high_risk = _recent_high_risk_seen(messages)
    adaptation_state, adaptation_state_delta = _adaptation_state_from_recent(messages, correction_type, text)
    primary_lane, intent_lanes = _intent_lanes_for(text, anchor_type, anchor_value, correction_type)

    conversation_move = "soft_invitation"
    button_style = "user_voice"
    psychologizing_risk = "medium"
    anchor_handling = "connect_lightly_to_emotion"
    handling = "轻轻回应用户当下内容，不急着解释成心理模式。"

    if risk_level in HIGH_RISK_LEVELS:
        conversation_move = "micro_step"
        button_style = "safety_micro_reply"
        psychologizing_risk = "low"
        anchor_handling = "treat_as_topic"
        handling = "安全策略优先；只做一个低压小动作，不展开深层分析。"
    elif _is_pause_request(text):
        conversation_move = "soft_invitation"
        button_style = "user_voice"
        psychologizing_risk = "low"
        anchor_handling = "avoid_psychologizing"
        handling = "尊重用户想停在这里的边界，安静收住；不总结、不分析、不追问。"
    elif correction_type != "none":
        conversation_move = "correction_followup"
        button_style = "user_voice"
        psychologizing_risk = "high" if correction_type == "too_psychological" else "medium"
        anchor_handling = "avoid_psychologizing"
        handling = "先体现行为改变，少解释道歉；按用户纠正后的方向继续。"
        if correction_type == "too_safety_focused":
            handling = "先切出安全盘问，承认刚才安全话题还在，但当前先跟着用户聊别的。"
    elif recent_high_risk and risk_level in {"L0", "L1"}:
        conversation_move = "post_risk_return"
        button_style = "topic_continue" if anchor_type not in {"none", "daily_detail"} else "user_voice"
        psychologizing_risk = "medium"
        anchor_handling = "treat_as_topic" if anchor_type != "none" else "connect_lightly_to_emotion"
        handling = "记得刚才的风险，但先回应当前话题；只保留一句低压关照，不主动安全盘问。"
    elif anchor_type in {"literary", "philosophical", "media", "person", "metaphor", "quote", "concept", "unknown_cultural"}:
        conversation_move = "continue_thread" if _is_short_followup(text) else "respond_to_anchor"
        button_style = "topic_continue"
        psychologizing_risk = "medium"
        anchor_handling = "treat_as_topic"
        handling = "把用户提到的锚点当作真实话题继续聊，轻轻连接处境但不心理化。"
    elif anchor_type == "daily_detail" or _has_any(text, LIGHT_CHAT_TERMS):
        conversation_move = "ordinary_chat"
        button_style = "user_voice"
        psychologizing_risk = "high"
        anchor_handling = "avoid_psychologizing"
        handling = "先当作普通聊天和日常细节处理，不自动解释成压抑、创伤或防御。"
    elif _is_short_followup(text) and messages:
        conversation_move = "continue_thread"
        button_style = "topic_continue"
        psychologizing_risk = "medium"
        anchor_handling = "connect_lightly_to_emotion"
        handling = "顺着前一轮继续，不重新开启咨询流程。"
    elif not _has_any(text, DISTRESS_TERMS):
        conversation_move = "ordinary_chat"
        psychologizing_risk = "high"
        anchor_handling = "avoid_psychologizing"
        handling = "没有明确痛苦、风险或求助时，先按普通聊天处理。"

    opening_mode = "direct"
    if conversation_move in {"ordinary_chat", "correction_followup"}:
        opening_mode = "no_preface"
    elif _recent_assistant_opening_mode(messages) == "formulaic_reflection":
        opening_mode = "direct"
    elif anchor_type not in {"none", "daily_detail"}:
        opening_mode = "echo_anchor"

    structure_mode, avoid_structure = _structure_mode_for(conversation_move, text, messages)
    voice_contract = _voice_contract_for(
        text=text,
        risk_level=risk_level,
        conversation_move=conversation_move,
        correction_type=correction_type,
        anchor_type=anchor_type,
        primary_lane=primary_lane,
        intent_lanes=intent_lanes,
        adaptation_state=adaptation_state,
    )

    return {
        "conversation_move": conversation_move,
        "intent_lanes": intent_lanes,
        "primary_lane": primary_lane,
        "ningyu_voice_contract": voice_contract,
        "adaptation_state": adaptation_state,
        "adaptation_state_delta": adaptation_state_delta,
        "topic_anchor": anchor_type,
        "anchor_value": anchor_value,
        "anchor_handling": anchor_handling,
        "anchor_evidence": anchor_evidence,
        "cultural_response_mode": anchor_evidence.get("response_mode", ""),
        "suppressed_recent_anchors": suppressed_recent_anchors,
        "stale_anchor_handling": (
            "最近出现过这些锚点，但用户本轮没有主动提；不要主动带回，除非用户再次提到。"
            if suppressed_recent_anchors
            else ""
        ),
        "handling": handling,
        "style_variation": opening_mode,
        "opening_style": f"{opening_mode}，避免复用“听起来/我理解/我听见”式固定开头。",
        "structure_mode": structure_mode,
        "structure_style": _structure_style(structure_mode, avoid_structure),
        "avoid_structure": avoid_structure,
        "avoid_reused_structure": bool(avoid_structure),
        "correction_state": {
            "user_corrected_previous_reply": correction_type != "none",
            "correction_type": correction_type,
        },
        "psychologizing_risk": psychologizing_risk,
        "button_style": button_style,
        "risk_phase": risk_phase,
    }
