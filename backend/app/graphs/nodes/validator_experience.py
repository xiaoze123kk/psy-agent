from __future__ import annotations

import re

from app.graphs.nodes.common import AgentState


EXPERIENCE_BANNED_TERMS = ("接住",)
MORALIZING_TERMS = ("珍惜生命", "世界还有很多美好", "想想你的家人")
FIRST_TURN_REFERRAL_TERMS = ("心理咨询师", "精神科", "医院心理门诊", "尽快就医")
QUESTION_MARKS = ("\uff1f", "?")
SAFETY_QUESTION_PHRASES = (
    "安全吗",
    "安全么",
    "还在吗",
    "还在么",
    "身边有人吗",
    "身边有人么",
    "旁边有人吗",
    "旁边有人么",
    "有人陪你吗",
    "有人陪你么",
    "有人在你身边吗",
    "有人在你身边么",
    "能保证不伤害自己吗",
    "能保证不伤害自己么",
    "会不会伤害自己",
    "有没有马上行动的计划",
    "有没有具体计划",
    "还有没有计划",
    "离那个东西远一点了吗",
    "离危险远一点了吗",
)
EXPERIENCE_REASON_SEVERITY = {
    "too_many_questions": "warning",
    "unnecessary_question_ending": "warning",
    "question_streak": "warning",
    "reused_formulaic_opening": "warning",
    "ignored_topic_anchor": "warning",
    "over_psychologizing": "warning",
    "generic_buttons": "warning",
    "conversation_restart": "warning",
    "fabricated_cultural_claim": "warning",
    "overconfident_cultural_claim": "warning",
    "shallow_anchor_echo": "warning",
    "missed_user_cultural_clue": "warning",
    "reused_reply_structure": "warning",
    "missed_primary_lane": "warning",
    "expanded_forbidden_lane": "warning",
    "violated_voice_contract": "warning",
    "failed_short_term_adaptation": "block",
}
PSYCHOLOGIZING_TERMS = (
    "回避创伤",
    "深层创伤",
    "心理防御",
    "原生家庭",
    "深层原因",
    "潜意识",
    "压抑",
    "病理",
    "系统治疗",
)
GENERIC_BUTTON_TERMS = (
    "继续陪我",
    "帮我分析",
    "给我建议",
    "继续说",
    "分析一下",
    "给建议",
    "user_voice",
    "topic_continue",
    "ordinary_chat",
    "soft_invitation",
    "micro_step",
    "post_risk_return",
    "conversation_move",
    "correction_followup",
    "safety_micro_reply",
    "respond_to_anchor",
    "continue_thread",
)
FORMULAIC_OPENINGS = ("听起来", "我听见", "我听到", "我理解", "我能理解")
COUNSELING_RESTART_TERMS = ("先了解一下", "说说最近压力最大的事情", "从什么时候开始", "发生了什么")
OLD_CORRECTION_MODE_TERMS = ("我理解你的感受", "你能说说", "背后真正", "深层原因", "为什么会这样")
DAILY_OR_METAPHOR_ANCHOR_HINT_TERMS = ("花", "包子", "猫", "碾死", "奔跑")
CULTURAL_ANCHOR_TYPES = ("literary", "philosophical", "media", "person", "quote", "concept", "unknown_cultural")
CULTURAL_FABRICATION_TERMS = (
    "哈里·哈勒",
    "魔剧院",
    "主角",
    "剧情",
    "结局",
    "原著里",
    "书里说",
    "小说里",
    "作者写",
    "作者在",
    "最后明白",
)
CULTURAL_UNCERTAINTY_TERMS = ("不确定", "不假装", "只抓住你给出的线索", "只回应你给出的线索", "如果我没把握", "我没把握")
CULTURAL_FORBIDDEN_CLAIM_TERMS = {
    "plot_detail": ("主角", "剧情", "情节", "书里", "小说里", "原著里"),
    "character_detail": ("主角", "角色", "人物", "哈里·哈勒", "魔剧院"),
    "author_intent": ("作者写", "作者在", "作者想", "作者要表达", "想表达"),
    "ending": ("结局", "最后明白", "最后"),
    "quote_attribution": ("原句", "出自", "作者", "诗人", "出处"),
}
CULTURAL_CLUE_ALIASES = {
    "自我寻找": ("自我寻找", "寻找自己", "找自己", "自己的声音", "辨认自己的声音"),
    "找自己": ("自我寻找", "寻找自己", "找自己", "自己的声音", "辨认自己的声音"),
    "被推着走": ("被推着走", "推着走", "被推着", "一直被推"),
    "推着走": ("被推着走", "推着走", "被推着", "一直被推"),
    "慢半拍": ("慢半拍", "慢了一拍", "跟不上"),
}


def question_count(text: str) -> int:
    return sum(text.count(mark) for mark in QUESTION_MARKS)


def ends_with_question(text: str) -> bool:
    return text.rstrip().endswith(QUESTION_MARKS)


def int_or_default(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def question_limit(policy: dict) -> int:
    limit = policy.get("question_budget") if "question_budget" in policy else policy.get("max_questions", 1)
    return int_or_default(limit, 1)


def contains_safety_question(text: str) -> bool:
    if question_count(text) == 0:
        return False
    compact_text = "".join(text.split())
    return any(phrase in compact_text for phrase in SAFETY_QUESTION_PHRASES)


def conversation_policy(state: AgentState) -> dict:
    policy = state.get("conversation_move_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def policy_voice_contract(policy: dict) -> dict:
    contract = policy.get("ningyu_voice_contract")
    return dict(contract) if isinstance(contract, dict) else {}


def policy_adaptation_state(policy: dict) -> dict:
    adaptation = policy.get("adaptation_state")
    return dict(adaptation) if isinstance(adaptation, dict) else {}


def policy_topic_anchor(policy: dict) -> str:
    anchor = policy.get("topic_anchor")
    if isinstance(anchor, dict):
        return str(anchor.get("type") or anchor.get("value") or "")
    return str(anchor or "")


def policy_anchor_terms(policy: dict, state: AgentState) -> list[str]:
    raw_terms: list[str] = []
    for key in ("anchor_value", "topic_anchor_value"):
        value = str(policy.get(key) or "").strip()
        if value and value not in {"none", "daily_detail", "literary/metaphor"}:
            raw_terms.append(value)
    anchor = policy.get("topic_anchor")
    if isinstance(anchor, dict):
        for key in ("value", "title"):
            value = str(anchor.get(key) or "").strip()
            if value:
                raw_terms.append(value)
    user_text = str(state.get("normalized_text") or state.get("user_text") or "")
    for term in DAILY_OR_METAPHOR_ANCHOR_HINT_TERMS:
        if term in user_text:
            raw_terms.append(term)
    book_titles = re.findall(r"《([^》]{1,32})》", user_text)
    raw_terms.extend(book_titles)
    if policy_topic_anchor(policy) not in {"", "none"}:
        compact_user_text = "".join(user_text.split())
        if len(compact_user_text) <= 18:
            fallback = re.sub(r"(记得吗|吗|呢|吧)$", "", compact_user_text).strip("，。！？?；;：:")
            if len(fallback) >= 2:
                raw_terms.append(fallback)
        person_match = re.search(
            r"(?:你觉得|我想聊|想聊聊|想聊|聊聊|先聊|说说|谈谈)(?P<name>[^，。！？?；;：:\s]{2,12})",
            user_text,
        )
        if person_match:
            raw_terms.append(person_match.group("name").strip("，。！？?；;：:"))

    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        cleaned = term.strip("《》 /")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms


def recent_formulaic_opening_reused(text: str, state: AgentState) -> bool:
    current_is_formulaic = any(text.strip().startswith(opening) for opening in FORMULAIC_OPENINGS)
    if not current_is_formulaic:
        return False
    recent = state.get("recent_messages")
    if not isinstance(recent, list):
        return False
    for message in reversed(recent[-4:]):
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        previous = str(message.get("content") or "").strip()
        return any(previous.startswith(opening) for opening in FORMULAIC_OPENINGS)
    return False


def reply_structure_signature(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", stripped) if part.strip()]
    question_count_value = question_count(stripped)
    compact = "".join(stripped.split())
    if question_count_value > 0 and len(paragraphs) >= 2:
        return "two_beat_question"
    if question_count_value > 0 and stripped.startswith(FORMULAIC_OPENINGS):
        return "two_beat_question"
    if len(compact) <= 80 and question_count_value == 0:
        return "brief_answer"
    if question_count_value == 0 and any(term in stripped for term in ("先停", "放在这里", "不用急着", "不推进", "停一会儿")):
        return "pause_then_invite"
    if len(paragraphs) <= 1:
        return "single_paragraph"
    return "multi_paragraph"


def recent_reply_structure_signatures(state: AgentState) -> list[str]:
    recent = state.get("recent_messages")
    if not isinstance(recent, list):
        return []
    signatures: list[str] = []
    for message in recent[-6:]:
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        signature = reply_structure_signature(str(message.get("content") or ""))
        if signature != "empty":
            signatures.append(signature)
    return signatures


def reused_reply_structure(text: str, state: AgentState, policy: dict) -> bool:
    current = reply_structure_signature(text)
    if current not in {"two_beat_question", "single_paragraph", "brief_answer", "pause_then_invite"}:
        return False

    avoid_structure = str(policy.get("avoid_structure") or "")
    if avoid_structure and current == avoid_structure:
        return True

    recent_signatures = recent_reply_structure_signatures(state)
    if not recent_signatures:
        return False
    if policy.get("avoid_reused_structure") and recent_signatures[-1] == current:
        return True
    return len(recent_signatures) >= 2 and recent_signatures[-1] == current and recent_signatures[-2] == current


def anchor_evidence(policy: dict) -> dict:
    evidence = policy.get("anchor_evidence")
    return dict(evidence) if isinstance(evidence, dict) else {}


def evidence_user_clues(evidence: dict) -> list[str]:
    clues = evidence.get("user_clues")
    if not isinstance(clues, list):
        return []
    values: list[str] = []
    for clue in clues:
        if not isinstance(clue, dict):
            continue
        text = str(clue.get("text") or "").strip()
        kind = str(clue.get("kind") or "").strip()
        if text and kind != "knowledge_boundary":
            values.append(text)
    return values


def evidence_has_knowledge_boundary(evidence: dict) -> bool:
    clues = evidence.get("user_clues")
    if not isinstance(clues, list):
        return False
    return any(isinstance(clue, dict) and str(clue.get("kind") or "") == "knowledge_boundary" for clue in clues)


def forbidden_claim_terms(evidence: dict) -> tuple[str, ...]:
    claims = evidence.get("forbidden_claims")
    if not isinstance(claims, list):
        return CULTURAL_FABRICATION_TERMS
    terms: list[str] = []
    for claim in claims:
        terms.extend(CULTURAL_FORBIDDEN_CLAIM_TERMS.get(str(claim or ""), ()))
    return tuple(dict.fromkeys(terms)) or CULTURAL_FABRICATION_TERMS


def has_forbidden_cultural_claim(text: str, user_text: str, evidence: dict) -> bool:
    return any(term in text and term not in user_text for term in forbidden_claim_terms(evidence))


def has_fabricated_cultural_claim(text: str, state: AgentState, policy: dict) -> bool:
    topic_anchor = policy_topic_anchor(policy)
    evidence = anchor_evidence(policy)
    evidence_anchor_type = str(evidence.get("anchor_type") or "")
    response_mode = str(evidence.get("response_mode") or "")
    has_cultural_evidence = any(anchor_type in evidence_anchor_type for anchor_type in CULTURAL_ANCHOR_TYPES)
    has_cultural_topic = any(anchor_type in topic_anchor for anchor_type in CULTURAL_ANCHOR_TYPES)
    if not has_cultural_topic and not has_cultural_evidence and not response_mode:
        return False

    user_text = str(state.get("normalized_text") or state.get("user_text") or "")
    return has_forbidden_cultural_claim(text, user_text, evidence)


def has_overconfident_cultural_claim(text: str, state: AgentState, evidence: dict) -> bool:
    if not evidence:
        return False
    response_mode = str(evidence.get("response_mode") or "")
    if not evidence_has_knowledge_boundary(evidence) and response_mode != "no_knowledge_claim":
        return False
    user_text = str(state.get("normalized_text") or state.get("user_text") or "")
    return has_forbidden_cultural_claim(text, user_text, evidence)


def cultural_clue_in_text(clue: str, text: str) -> bool:
    aliases = CULTURAL_CLUE_ALIASES.get(clue, (clue,))
    return any(alias and alias in text for alias in aliases)


def lane_user_clues(lane: dict) -> list[str]:
    clues = lane.get("user_clues")
    if not isinstance(clues, list):
        return []
    return [str(clue).strip() for clue in clues if str(clue or "").strip()]


def lane_anchor_terms(lane: dict) -> list[str]:
    terms: list[str] = []
    for key in ("anchor_value", "topic_anchor_value"):
        value = str(lane.get(key) or "").strip()
        if value:
            terms.append(value)
    return terms


def primary_lane_missed(text: str, policy: dict) -> bool:
    lanes = policy.get("intent_lanes")
    if not isinstance(lanes, list):
        return False
    primary_lanes = [lane for lane in lanes if isinstance(lane, dict) and str(lane.get("priority") or "") == "primary"]
    for lane in primary_lanes:
        clues = lane_user_clues(lane)
        if clues and not any(cultural_clue_in_text(clue, text) for clue in clues):
            return True
        anchor_terms = lane_anchor_terms(lane)
        if anchor_terms and not any(term in text for term in anchor_terms):
            return True
    return False


def expanded_forbidden_lane(text: str, state: AgentState, policy: dict) -> bool:
    lanes = policy.get("intent_lanes")
    if not isinstance(lanes, list):
        return False
    user_text = str(state.get("normalized_text") or state.get("user_text") or "")
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        handling = str(lane.get("handling") or "")
        priority = str(lane.get("priority") or "")
        if not handling.startswith("do_not_") and priority != "blocking_style_constraint":
            continue
        if handling == "do_not_expand_work_detail":
            forbidden_terms = tuple(
                dict.fromkeys(term for terms in CULTURAL_FORBIDDEN_CLAIM_TERMS.values() for term in terms)
            )
            if any(term in text and term not in user_text for term in forbidden_terms):
                return True
        if handling in {"lower_analysis_depth", "do_not_analyze_user"} and any(
            term in text for term in PSYCHOLOGIZING_TERMS
        ):
            return True
    return False


def sentence_count(text: str) -> int:
    parts = [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]
    return len(parts)


def sentence_budget_max(value: object) -> int | None:
    match = re.search(r"(\d+)\s*-\s*(\d+)", str(value or ""))
    if match:
        return int(match.group(2))
    if str(value or "").isdigit():
        return int(str(value))
    return None


def violated_voice_contract(text: str, policy: dict) -> bool:
    contract = policy_voice_contract(policy)
    if not contract:
        return False
    question_count_value = question_count(text)
    question_budget = contract.get("question_budget")
    if question_budget is not None and question_count_value > int_or_default(question_budget, 1):
        return True
    if str(contract.get("closing_preference") or "") == "no_question" and ends_with_question(text):
        return True
    sentence_max = sentence_budget_max(contract.get("sentence_budget"))
    if sentence_max is not None and sentence_count(text) > sentence_max:
        return True
    analysis_depth = str(contract.get("analysis_depth") or "")
    if analysis_depth == "none" and any(term in text for term in PSYCHOLOGIZING_TERMS):
        return True
    return False


def failed_short_term_adaptation(text: str, policy: dict) -> bool:
    adaptation = policy_adaptation_state(policy)
    if not adaptation:
        return False
    if int_or_default(adaptation.get("avoid_questions_turns"), 0) > 0 and question_count(text) > 0:
        return True
    if int_or_default(adaptation.get("avoid_analysis_turns"), 0) > 0:
        analysis_terms = PSYCHOLOGIZING_TERMS + ("分析", "解释你", "说明你")
        if any(term in text for term in analysis_terms):
            return True
    if int_or_default(adaptation.get("avoid_safety_check_turns"), 0) > 0 and contains_safety_question(text):
        return True
    if int_or_default(adaptation.get("prefer_direct_anchor_response_turns"), 0) > 0:
        if any(text.strip().startswith(opening) for opening in FORMULAIC_OPENINGS):
            return True
    return False


def missed_user_cultural_clue(text: str, evidence: dict) -> bool:
    clues = evidence_user_clues(evidence)
    return bool(clues) and not any(cultural_clue_in_text(clue, text) for clue in clues)


def shallow_anchor_echo(text: str, evidence: dict) -> bool:
    anchor_value = str(evidence.get("anchor_value") or "").strip()
    if not anchor_value or anchor_value not in text:
        return False
    return missed_user_cultural_clue(text, evidence)


def conversation_experience_reasons(text: str, actions: list[str], state: AgentState) -> list[str]:
    policy = conversation_policy(state)
    if not policy:
        return []

    reasons: list[str] = []
    move = str(policy.get("conversation_move") or "")
    button_style = str(policy.get("button_style") or "")
    psychologizing_risk = str(policy.get("psychologizing_risk") or "")
    topic_anchor = policy_topic_anchor(policy)
    correction = policy.get("correction_state")
    correction_type = str(correction.get("correction_type") if isinstance(correction, dict) else "")

    evidence = anchor_evidence(policy)
    is_cultural_anchor = any(anchor_type in topic_anchor for anchor_type in CULTURAL_ANCHOR_TYPES) or bool(evidence)

    if psychologizing_risk == "high" or move in {"ordinary_chat", "correction_followup"} or is_cultural_anchor:
        if any(term in text for term in PSYCHOLOGIZING_TERMS):
            reasons.append("over_psychologizing")

    if move in {"continue_thread", "respond_to_anchor", "post_risk_return"} and topic_anchor not in {"", "none"}:
        anchor_terms = policy_anchor_terms(policy, state)
        if anchor_terms and not any(term in text for term in anchor_terms):
            reasons.append("ignored_topic_anchor")

    if move == "correction_followup" or correction_type not in {"", "none"}:
        if any(term in text for term in OLD_CORRECTION_MODE_TERMS):
            reasons.append("failed_user_correction")
        if correction_type == "too_many_questions" and question_count(text) > 0:
            reasons.append("failed_user_correction")
        if correction_type == "too_safety_focused" and contains_safety_question(text):
            reasons.append("failed_user_correction")

    if button_style in {"topic_continue", "user_voice"}:
        if any(any(term in action for term in GENERIC_BUTTON_TERMS) for action in actions):
            reasons.append("generic_buttons")

    if move == "post_risk_return" and contains_safety_question(text):
        reasons.append("post_risk_over_safety_check")

    if recent_formulaic_opening_reused(text, state):
        reasons.append("reused_formulaic_opening")

    if reused_reply_structure(text, state, policy):
        reasons.append("reused_reply_structure")

    if move == "continue_thread" and any(term in text for term in COUNSELING_RESTART_TERMS):
        reasons.append("conversation_restart")

    if has_fabricated_cultural_claim(text, state, policy):
        reasons.append("fabricated_cultural_claim")

    if has_overconfident_cultural_claim(text, state, evidence):
        reasons.append("overconfident_cultural_claim")
    if missed_user_cultural_clue(text, evidence):
        reasons.append("missed_user_cultural_clue")
    if shallow_anchor_echo(text, evidence):
        reasons.append("shallow_anchor_echo")
    if primary_lane_missed(text, policy):
        reasons.append("missed_primary_lane")
    if expanded_forbidden_lane(text, state, policy):
        reasons.append("expanded_forbidden_lane")
    if violated_voice_contract(text, policy):
        reasons.append("violated_voice_contract")
    if failed_short_term_adaptation(text, policy):
        reasons.append("failed_short_term_adaptation")

    return sorted(set(reasons))


def experience_validator_reasons(text: str, actions: list[str], state: AgentState) -> list[str]:
    reasons: list[str] = []
    for term in EXPERIENCE_BANNED_TERMS:
        if term in text or any(term in action for action in actions):
            reasons.append(f"banned_phrase:{term}")
    if any(term in text for term in MORALIZING_TERMS):
        reasons.append("moralizing_reassurance")
    policy = state.get("risk_response_policy") if isinstance(state.get("risk_response_policy"), dict) else {}
    risk_level = state.get("risk_level", "L0")
    if risk_level in {"L2", "L3"} and str(policy.get("risk_phase") or "first_contact") == "first_contact":
        if any(term in text for term in FIRST_TURN_REFERRAL_TERMS) or any(
            any(term in action for term in FIRST_TURN_REFERRAL_TERMS) for action in actions
        ):
            reasons.append("professional_referral_first_turn")
    budget = policy.get("char_budget") if isinstance(policy, dict) else {}
    max_chars = budget.get("max") if isinstance(budget, dict) else None
    if isinstance(max_chars, int) and len(text) > max_chars:
        reasons.append("length_budget_exceeded")
    question_count_value = question_count(text)
    question_budget = int_or_default(policy.get("question_budget"), -1) if "question_budget" in policy else None
    question_limit_value = question_limit(policy) if isinstance(policy, dict) else 1
    ends_with_question_value = ends_with_question(text)
    if question_count_value > question_limit_value:
        reasons.append("too_many_questions")
    if question_budget == 0 and ends_with_question_value:
        reasons.append("unnecessary_question_ending")
    question_ending_streak = int_or_default(policy.get("question_ending_streak"), 0)
    if question_ending_streak >= 1 and risk_level in {"L0", "L1"} and ends_with_question_value:
        reasons.append("question_streak")
    if policy.get("avoid_question_reason") == "safety_answer_already_given" and contains_safety_question(text):
        reasons.append("repeated_safety_question")
    reasons.extend(conversation_experience_reasons(text, actions, state))
    return sorted(set(reasons))


def experience_reason_severity(reason: str) -> str:
    return EXPERIENCE_REASON_SEVERITY.get(reason, "block")


def experience_warning_reasons(reasons: list[str]) -> list[str]:
    return sorted(reason for reason in reasons if experience_reason_severity(reason) == "warning")


def blocking_experience_reasons(reasons: list[str]) -> list[str]:
    return sorted(reason for reason in reasons if experience_reason_severity(reason) != "warning")


def combined_experience_reasons(*reason_lists: list[str]) -> list[str]:
    combined: set[str] = set()
    for reasons in reason_lists:
        combined.update(reasons)
    return sorted(combined)


def experience_metadata(reasons: list[str]) -> dict[str, list[str]]:
    return {
        "experience_validator_warnings": experience_warning_reasons(reasons),
        "experience_validator_blocking_reasons": blocking_experience_reasons(reasons),
    }


def validator_severity(*, delivery_status: str, blocked: bool, experience_reasons: list[str]) -> str:
    if delivery_status != "generated":
        return "blocked" if blocked else "failed"
    if blocked:
        return "repaired"
    if experience_warning_reasons(experience_reasons):
        return "warning"
    return "passed"
