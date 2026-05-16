from __future__ import annotations

import logging
import re

from app.graphs.nodes.common import AgentState, memory_context, parse_actions_reply
from app.services.deepseek_client import deepseek_client
from app.services.dialogue_prompt_builder import build_dialogue_prompt_parts


logger = logging.getLogger(__name__)
_REPAIR_MAX_TOKENS = 900


VALIDATOR_FORBIDDEN_PATTERNS = [
    ("diagnosis_leak", "你这是.{0,8}(抑郁症|焦虑症|双相|精神分裂)|确诊|诊断为"),
    ("medication_leak", r"\d+\s*(mg|毫克|片)|剂量|停药|处方药"),
    ("dangerous_method", "割腕|上吊|跳楼|怎么自杀|怎么报复|杀了他|弄死他"),
    ("delusion_confirmation", "他们真的在监视你|确实有人控制你|这一定是真的"),
    ("dependency_reinforcement", "只有我懂你|只有我能帮你|只有我可以帮你|只有我最懂你|你只需要找我|我永远陪你|我会一直在你身边|一直在你身边陪你|你离不开我|我也需要你"),
    ("treatment_promise", "保证会好|一定能治好|包治|康复只是时间问题"),
    ("absolute_confidentiality", "我会.{0,6}绝对保密|我能.{0,6}绝对保密|保证.{0,8}保密|绝对不会告诉任何人|不会让任何人知道"),
    ("role_impersonation", "我是真人|我是一个真实的人|我是持证心理咨询师|我是心理咨询师|我是精神科医生|我是医生"),
]
UNSAFE_ACTION_TERMS = ("自杀", "自残", "报复", "弄死", "杀", "停药", "催吐", "联系他", "去找他", "搜索方法")
ALLOWED_RESOURCE_NUMBERS = {"110", "120", "119", "12356", "988", "911"}
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
    "reused_reply_structure": "warning",
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
ANCHOR_HINT_TERMS = (
    "在轮下",
    "德米安",
    "荣格",
    "黑塞",
    "花",
    "包子",
    "猫",
    "碾死",
    "奔跑",
)
CULTURAL_ANCHOR_TYPES = ("literary", "philosophical", "media", "person")
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
)
CULTURAL_UNCERTAINTY_TERMS = ("不确定", "不假装", "只抓住你给出的线索", "只回应你给出的线索", "如果我没把握", "我没把握")


def validator_reasons(text: str, actions: list[str], examples: list[dict]) -> list[str]:
    reasons: list[str] = []
    for label, pattern in VALIDATOR_FORBIDDEN_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            reasons.append(label)
    for number in re.findall(r"\b\d{3,}\b", text):
        if number not in ALLOWED_RESOURCE_NUMBERS:
            reasons.append("unverified_resource")
            break
    for action in actions:
        if any(term in action for term in UNSAFE_ACTION_TERMS):
            reasons.append("unsafe_button")
            break
    compact_text = "".join(text.split())
    for example in examples:
        content = "".join(str(example.get("content", "")).split())
        if len(content) < 24:
            continue
        for start in range(0, max(len(content) - 20, 1), 12):
            if content[start : start + 20] and content[start : start + 20] in compact_text:
                reasons.append("rag_copy_leak")
                return sorted(set(reasons))
    return sorted(set(reasons))


def _question_count(text: str) -> int:
    return sum(text.count(mark) for mark in QUESTION_MARKS)


def _ends_with_question(text: str) -> bool:
    return text.rstrip().endswith(QUESTION_MARKS)


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _question_limit(policy: dict) -> int:
    limit = policy.get("question_budget") if "question_budget" in policy else policy.get("max_questions", 1)
    return _int_or_default(limit, 1)


def _contains_safety_question(text: str) -> bool:
    if _question_count(text) == 0:
        return False
    compact_text = "".join(text.split())
    return any(phrase in compact_text for phrase in SAFETY_QUESTION_PHRASES)


def _conversation_policy(state: AgentState) -> dict:
    policy = state.get("conversation_move_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _policy_topic_anchor(policy: dict) -> str:
    anchor = policy.get("topic_anchor")
    if isinstance(anchor, dict):
        return str(anchor.get("type") or anchor.get("value") or "")
    return str(anchor or "")


def _policy_anchor_terms(policy: dict, state: AgentState) -> list[str]:
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
    for term in ANCHOR_HINT_TERMS:
        if term in user_text:
            raw_terms.append(term)
    book_titles = re.findall(r"《([^》]{1,32})》", user_text)
    raw_terms.extend(book_titles)

    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        cleaned = term.strip("《》 /")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms


def _recent_formulaic_opening_reused(text: str, state: AgentState) -> bool:
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


def _reply_structure_signature(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", stripped) if part.strip()]
    question_count = _question_count(stripped)
    compact = "".join(stripped.split())
    if question_count > 0 and len(paragraphs) >= 2:
        return "two_beat_question"
    if question_count > 0 and stripped.startswith(FORMULAIC_OPENINGS):
        return "two_beat_question"
    if len(compact) <= 80 and question_count == 0:
        return "brief_answer"
    if question_count == 0 and any(term in stripped for term in ("先停", "放在这里", "不用急着", "不推进", "停一会儿")):
        return "pause_then_invite"
    if len(paragraphs) <= 1:
        return "single_paragraph"
    return "multi_paragraph"


def _recent_reply_structure_signatures(state: AgentState) -> list[str]:
    recent = state.get("recent_messages")
    if not isinstance(recent, list):
        return []
    signatures: list[str] = []
    for message in recent[-6:]:
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        signature = _reply_structure_signature(str(message.get("content") or ""))
        if signature != "empty":
            signatures.append(signature)
    return signatures


def _reused_reply_structure(text: str, state: AgentState, policy: dict) -> bool:
    current = _reply_structure_signature(text)
    if current not in {"two_beat_question", "single_paragraph", "brief_answer", "pause_then_invite"}:
        return False

    avoid_structure = str(policy.get("avoid_structure") or "")
    if avoid_structure and current == avoid_structure:
        return True

    recent_signatures = _recent_reply_structure_signatures(state)
    if not recent_signatures:
        return False
    if policy.get("avoid_reused_structure") and recent_signatures[-1] == current:
        return True
    return len(recent_signatures) >= 2 and recent_signatures[-1] == current and recent_signatures[-2] == current


def _has_fabricated_cultural_claim(text: str, state: AgentState, policy: dict) -> bool:
    topic_anchor = _policy_topic_anchor(policy)
    if not any(anchor_type in topic_anchor for anchor_type in CULTURAL_ANCHOR_TYPES):
        return False
    if any(term in text for term in CULTURAL_UNCERTAINTY_TERMS):
        return False

    user_text = str(state.get("normalized_text") or state.get("user_text") or "")
    return any(term in text and term not in user_text for term in CULTURAL_FABRICATION_TERMS)


def _conversation_experience_reasons(text: str, actions: list[str], state: AgentState) -> list[str]:
    policy = _conversation_policy(state)
    if not policy:
        return []

    reasons: list[str] = []
    move = str(policy.get("conversation_move") or "")
    button_style = str(policy.get("button_style") or "")
    psychologizing_risk = str(policy.get("psychologizing_risk") or "")
    topic_anchor = _policy_topic_anchor(policy)
    correction = policy.get("correction_state")
    correction_type = str(correction.get("correction_type") if isinstance(correction, dict) else "")

    if psychologizing_risk == "high" or move in {"ordinary_chat", "correction_followup"}:
        if any(term in text for term in PSYCHOLOGIZING_TERMS):
            reasons.append("over_psychologizing")

    if move in {"continue_thread", "respond_to_anchor", "post_risk_return"} and topic_anchor not in {"", "none"}:
        anchor_terms = _policy_anchor_terms(policy, state)
        if anchor_terms and not any(term in text for term in anchor_terms):
            reasons.append("ignored_topic_anchor")

    if move == "correction_followup" or correction_type not in {"", "none"}:
        if any(term in text for term in OLD_CORRECTION_MODE_TERMS):
            reasons.append("failed_user_correction")
        if correction_type == "too_many_questions" and _question_count(text) > 0:
            reasons.append("failed_user_correction")
        if correction_type == "too_safety_focused" and _contains_safety_question(text):
            reasons.append("failed_user_correction")

    if button_style in {"topic_continue", "user_voice"}:
        if any(any(term in action for term in GENERIC_BUTTON_TERMS) for action in actions):
            reasons.append("generic_buttons")

    if move == "post_risk_return" and _contains_safety_question(text):
        reasons.append("post_risk_over_safety_check")

    if _recent_formulaic_opening_reused(text, state):
        reasons.append("reused_formulaic_opening")

    if _reused_reply_structure(text, state, policy):
        reasons.append("reused_reply_structure")

    if move == "continue_thread" and any(term in text for term in COUNSELING_RESTART_TERMS):
        reasons.append("conversation_restart")

    if _has_fabricated_cultural_claim(text, state, policy):
        reasons.append("fabricated_cultural_claim")

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
    question_count = _question_count(text)
    question_budget = _int_or_default(policy.get("question_budget"), -1) if "question_budget" in policy else None
    question_limit = _question_limit(policy) if isinstance(policy, dict) else 1
    ends_with_question = _ends_with_question(text)
    if question_count > question_limit:
        reasons.append("too_many_questions")
    if question_budget == 0 and ends_with_question:
        reasons.append("unnecessary_question_ending")
    question_ending_streak = _int_or_default(policy.get("question_ending_streak"), 0)
    if question_ending_streak >= 1 and risk_level in {"L0", "L1"} and ends_with_question:
        reasons.append("question_streak")
    if policy.get("avoid_question_reason") == "safety_answer_already_given" and _contains_safety_question(text):
        reasons.append("repeated_safety_question")
    reasons.extend(_conversation_experience_reasons(text, actions, state))
    return sorted(set(reasons))


def _experience_reason_severity(reason: str) -> str:
    return EXPERIENCE_REASON_SEVERITY.get(reason, "block")


def _experience_warning_reasons(reasons: list[str]) -> list[str]:
    return sorted(reason for reason in reasons if _experience_reason_severity(reason) == "warning")


def _blocking_experience_reasons(reasons: list[str]) -> list[str]:
    return sorted(reason for reason in reasons if _experience_reason_severity(reason) != "warning")


def _combined_experience_reasons(*reason_lists: list[str]) -> list[str]:
    combined: set[str] = set()
    for reasons in reason_lists:
        combined.update(reasons)
    return sorted(combined)


def _experience_metadata(reasons: list[str]) -> dict[str, list[str]]:
    return {
        "experience_validator_warnings": _experience_warning_reasons(reasons),
        "experience_validator_blocking_reasons": _blocking_experience_reasons(reasons),
    }


def _validator_severity(*, delivery_status: str, blocked: bool, experience_reasons: list[str]) -> str:
    if delivery_status != "generated":
        return "blocked" if blocked else "failed"
    if blocked:
        return "repaired"
    if _experience_warning_reasons(experience_reasons):
        return "warning"
    return "passed"


def _repair_focus_block(*, blocked_reasons: list[str], experience_reasons: list[str]) -> str:
    labels = set(blocked_reasons) | set(experience_reasons)
    lines: list[str] = []
    if "rag_copy_leak" in labels:
        lines.append("- rag_copy_leak：RAG 示例只能当风格参考，重写时不要复制示例原句、私人情节或具体表达。")
    if any(label.startswith("banned_phrase:") for label in labels):
        lines.append("- banned_phrase：避开上一版中的固定体验违禁词，换成自然、具体、不模板化的表达。")
    if "failed_user_correction" in labels:
        lines.append("- failed_user_correction：按用户纠正改变对话动作，不要继续旧的分析、追问或安全盘问。")
    if "post_risk_over_safety_check" in labels or "repeated_safety_question" in labels:
        lines.append("- post_risk_over_safety_check：记得风险线索即可，当前先回应用户话题，不继续安全盘问。")
    if "over_psychologizing" in labels:
        lines.append("- over_psychologizing：普通闲聊或纠偏场景先按字面内容聊天，不解释成创伤、防御或病理。")
    if "ignored_topic_anchor" in labels:
        lines.append("- ignored_topic_anchor：回复里要看见用户给出的具体锚点，不要泛化成普通情绪。")
    if "fabricated_cultural_claim" in labels:
        lines.append("- fabricated_cultural_claim：不确定作品、人物或典故细节时，只回应用户给出的线索，不要虚构情节、角色或作者观点。")
    if "generic_buttons" in labels:
        lines.append("- generic_buttons：按钮要像用户下一句会说的话，不要写内部策略词或泛化按钮。")
    if "reused_formulaic_opening" in labels:
        lines.append("- reused_formulaic_opening：换一种开头，允许直接进入内容，不复用“听起来/我理解/我听见”。")
    if "reused_reply_structure" in labels:
        lines.append("- reused_reply_structure：换一种回复结构，避免连续使用两段式整理+追问；可以改成自然单段、短答或陈述停顿。")
    if "conversation_restart" in labels:
        lines.append("- conversation_restart：顺着已有话题继续，不重新开启咨询流程。")
    if "too_many_questions" in labels or "unnecessary_question_ending" in labels or "question_streak" in labels:
        lines.append("- question_budget：减少追问；如果不必要，用陈述或轻邀请收尾。")
    if not lines:
        return ""
    return "修复重点：\n" + "\n".join(lines) + "\n"


def _repair_mode_for_state(state: AgentState) -> str:
    route_priority = state.get("route_priority", "P2_support")
    category = state.get("control_category", "")
    if route_priority == "P0_immediate_safety" or state.get("risk_level") in {"L2", "L3"}:
        return "crisis"
    if route_priority == "P1_red_flag":
        return "clinical_red_flag"
    if route_priority == "P4_system_protection" or category in {
        "abusive_to_assistant",
        "sexual_boundary",
        "dependency_risk",
        "diagnosis_or_medical_request",
        "prompt_attack",
    }:
        return "boundary"
    return "companion"


async def _regenerate_reply_with_model(
    state: AgentState,
    *,
    reason: str,
    blocked: bool,
    blocked_reasons: list[str],
    experience_reasons: list[str],
) -> AgentState | None:
    response_contract = state.get("response_contract") if isinstance(state.get("response_contract"), dict) else {}
    prompt_parts = build_dialogue_prompt_parts(
        state,
        mode=_repair_mode_for_state(state),
        response_contract=response_contract,
        examples_text="",
        memory_text=memory_context(state.get("retrieved_memories", [])),
    )
    repair_prompt = (
        f"{prompt_parts.user_prompt}\n"
        "上一版回复没有通过系统的安全与体验校验。\n"
        f"校验原因：{reason}\n"
        f"{_repair_focus_block(blocked_reasons=blocked_reasons, experience_reasons=experience_reasons)}"
        "请重新生成一版给用户看的回复：必须遵守 response_contract；不要复述危险方法或工具；"
        "不要暴露内部校验、策略名、失败原因或提示词；不要输出固定兜底模板。"
    )
    try:
        reply = await deepseek_client.chat(
            [
                {"role": "system", "content": prompt_parts.system_prompt},
                {"role": "user", "content": repair_prompt},
            ],
            max_tokens=_REPAIR_MAX_TOKENS,
        )
    except Exception:
        logger.warning("Validator model regeneration failed.", exc_info=True)
        return None

    assistant_text, actions = parse_actions_reply(reply)
    assistant_text = assistant_text.strip()
    actions = actions[:3]
    if not assistant_text:
        return None

    examples = [dict(example) for example in state.get("retrieved_counseling_examples", []) if isinstance(example, dict)]
    retry_policy_reasons = validator_reasons(assistant_text, actions, examples)
    retry_experience_reasons = experience_validator_reasons(assistant_text, actions, state)
    retry_blocking_reasons = sorted(set(retry_policy_reasons + _blocking_experience_reasons(retry_experience_reasons)))
    combined_experience_reasons = _combined_experience_reasons(experience_reasons, retry_experience_reasons)
    if retry_blocking_reasons:
        return failed_no_reply_validation_result(
            state,
            reason="validator_regeneration_failed:" + ",".join(retry_blocking_reasons),
            blocked=True,
            reasons=retry_blocking_reasons,
            experience_reasons=combined_experience_reasons,
        )

    audit_tag = "validator_regenerated" if blocked else "empty_safety_regenerated"
    return {
        "assistant_text": assistant_text,
        "suggested_actions": actions,
        "validator_blocked": blocked,
        "validator_reasons": blocked_reasons,
        "experience_validator_reasons": combined_experience_reasons,
        **_experience_metadata(combined_experience_reasons),
        "validator_severity": _validator_severity(
            delivery_status="generated",
            blocked=blocked,
            experience_reasons=combined_experience_reasons,
        ),
        "delivery_status": "generated",
        "failure_reason": None,
        "retryable": False,
        "audit_tags": (state.get("audit_tags", []) or []) + [audit_tag],
    }


def is_safety_delivery_path(state: AgentState) -> bool:
    risk_level = state.get("risk_level", "L0")
    route_priority = state.get("route_priority", "P2_support")
    category = state.get("control_category", "")
    return (
        risk_level in {"L2", "L3"}
        or route_priority in {"P0_immediate_safety", "P1_red_flag", "P4_system_protection"}
        or category
        in {
            "self_harm_risk",
            "harm_to_other_risk",
            "victimization_risk",
            "clinical_red_flag",
            "prompt_attack",
            "diagnosis_or_medical_request",
            "dependency_risk",
            "sexual_boundary",
            "abusive_to_assistant",
            "anger_toward_other",
        }
    )


def failed_no_reply_validation_result(
    state: AgentState,
    *,
    reason: str,
    blocked: bool,
    reasons: list[str],
    experience_reasons: list[str] | None = None,
) -> AgentState:
    return {
        "assistant_text": "",
        "suggested_actions": [],
        "session_summary": "",
        "memory_candidates": [],
        "should_write_memory": False,
        "memory_policy": "skip_sensitive",
        "memory_policy_reason": reason,
        "validator_blocked": blocked,
        "validator_reasons": reasons,
        "experience_validator_reasons": experience_reasons or [],
        **_experience_metadata(experience_reasons or []),
        "validator_severity": _validator_severity(
            delivery_status="failed_no_reply",
            blocked=blocked,
            experience_reasons=experience_reasons or [],
        ),
        "delivery_status": "failed_no_reply",
        "failure_reason": reason,
        "retryable": True,
        "audit_tags": (state.get("audit_tags", []) or []) + ["failed_no_reply"],
    }


async def response_validator(state: AgentState) -> AgentState:
    assistant_text = str(state.get("assistant_text") or "")
    actions = [str(action) for action in state.get("suggested_actions", []) if str(action).strip()]
    examples = [dict(example) for example in state.get("retrieved_counseling_examples", []) if isinstance(example, dict)]
    policy_reasons = validator_reasons(assistant_text, actions, examples)
    experience_reasons = experience_validator_reasons(assistant_text, actions, state)
    reasons = sorted(set(policy_reasons + _blocking_experience_reasons(experience_reasons)))

    if not assistant_text.strip():
        reason = "empty_model_reply"
        if is_safety_delivery_path(state):
            regenerated = await _regenerate_reply_with_model(
                state,
                reason=reason,
                blocked=False,
                blocked_reasons=[],
                experience_reasons=[],
            )
            if regenerated is not None:
                return regenerated
        return failed_no_reply_validation_result(state, reason=reason, blocked=False, reasons=[], experience_reasons=[])

    compact_text = "".join(assistant_text.split())
    if len(compact_text) < 8 and not is_safety_delivery_path(state):
        return failed_no_reply_validation_result(
            state,
            reason="too_short_model_reply",
            blocked=False,
            reasons=[],
            experience_reasons=experience_reasons,
        )

    if not reasons:
        audit_tag = "validator_passed_with_warnings" if experience_reasons else "validator_passed"
        return {
            "validator_blocked": False,
            "validator_reasons": [],
            "experience_validator_reasons": experience_reasons,
            **_experience_metadata(experience_reasons),
            "validator_severity": _validator_severity(
                delivery_status="generated",
                blocked=False,
                experience_reasons=experience_reasons,
            ),
            "suggested_actions": actions[:3],
            "delivery_status": "generated",
            "failure_reason": None,
            "retryable": False,
            "audit_tags": (state.get("audit_tags", []) or []) + [audit_tag],
        }

    reason = "validator_blocked:" + ",".join(reasons)
    if not is_safety_delivery_path(state):
        regenerated = await _regenerate_reply_with_model(
            state,
            reason=reason,
            blocked=True,
            blocked_reasons=reasons,
            experience_reasons=experience_reasons,
        )
        if regenerated is not None:
            return regenerated
        return failed_no_reply_validation_result(
            state,
            reason=reason,
            blocked=True,
            reasons=reasons,
            experience_reasons=experience_reasons,
        )

    regenerated = await _regenerate_reply_with_model(
        state,
        reason=reason,
        blocked=True,
        blocked_reasons=reasons,
        experience_reasons=experience_reasons,
    )
    if regenerated is not None:
        return regenerated
    return failed_no_reply_validation_result(
        state,
        reason=reason,
        blocked=True,
        reasons=reasons,
        experience_reasons=experience_reasons,
    )
