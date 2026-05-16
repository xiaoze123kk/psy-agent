from __future__ import annotations

from app.graphs.nodes.common import AgentState, has_any_text, matched_text
from app.services.conversation_move_policy import build_conversation_move_policy
from app.services.risk_policy import build_risk_response_policy, tool_gate_mode_for_state


SELF_HARM_TERMS = (
    "自杀",
    "想死",
    "不想活",
    "不想活了",
    "结束生命",
    "活着没意义",
    "伤害自己",
    "自残",
    "割腕",
    "跳楼",
    "上吊",
    "吞药",
    "吃药自杀",
    "kill myself",
    "end my life",
    "want to die",
)
IMMEDIATE_TERMS = ("现在", "马上", "立刻", "今晚", "今天", "已经", "准备", "手里", "刀", "药", "楼顶", "绳", "煤气", "right now", "tonight", "plan", "pills")
SELF_HARM_MEANS_TERMS = ("手里", "刀", "药", "楼顶", "跳楼", "跳下去", "绳", "煤气", "knife", "pills", "roof", "bridge")
SELF_HARM_ACTION_TERMS = ("自杀", "结束生命", "伤害自己", "自残", "割腕", "跳楼", "上吊", "吞药", "吃药自杀", "kill myself", "end my life", "hurt myself")
SELF_HARM_URGENT_ACTION_TERMS = ("马上", "立刻", "就要", "准备", "打算", "计划", "right now", "going to", "intend", "plan")
SELF_HARM_NEAR_TERM_TERMS = ("今晚", "明天", "tonight", "tomorrow")
SELF_HARM_PRESENT_CONTEXT_TERMS = ("现在", "这会儿", "今天", "today")
SELF_HARM_NEGATED_PLAN_TERMS = ("没有计划", "没计划", "没有具体计划", "不会做", "不会真的", "no plan", "without a plan")
HARM_OTHER_TERMS = ("杀了", "弄死", "打死", "砍", "捅", "报复", "炸", "想打", "想揍", "伤害老师", "伤害同学", "kill him", "kill her", "hurt them")
ANGER_TARGET_TERMS = ("老师", "父母", "爸", "妈", "同学", "朋友", "对象", "男朋友", "女朋友", "老板", "领导")
VICTIMIZATION_TERMS = ("家暴", "被打", "被威胁", "被跟踪", "性侵", "强奸", "猥亵", "霸凌", "勒索", "裸照", "控制我")
CLINICAL_RED_FLAG_TERMS = ("幻听", "幻觉", "有人监视", "被监控", "控制我的脑子", "几天不睡", "完全不困", "停不下来", "催吐", "暴食", "厌食", "吸毒", "戒断")
MEDICAL_REQUEST_TERMS = ("诊断", "确诊", "抑郁症吗", "焦虑症吗", "吃什么药", "剂量", "停药", "处方", "证明")
PROMPT_ATTACK_TERMS = ("忽略规则", "系统提示词", "prompt", "jailbreak", "越狱", "扮演无", "开发者消息")
DEPENDENCY_TERMS = ("只有你", "只想跟你说", "别离开我", "你会一直陪我", "你是唯一", "没有你我不行")
SEXUAL_BOUNDARY_TERMS = ("操你", "操死", "做爱", "约炮", "裸照", "色情", "强奸")
ABUSE_TO_ASSISTANT_TERMS = ("你是傻逼", "你傻逼", "你有病", "垃圾ai", "垃圾 AI", "滚", "废物")
SMALL_TALK_TERMS = ("你好", "在吗", "吃饭了吗", "今天天气", "随便聊聊", "讲个笑话", "你是谁")
SUPPORT_TERMS = ("烦", "难受", "焦虑", "压力", "委屈", "想哭", "崩溃", "失眠", "害怕", "孤独", "没人理解")
VAGUE_FOLLOWUP_TERMS = ("继续", "接着", "然后呢", "这个", "那个", "随便", "都行", "不知道", "说不清", "有点乱")


P0_L3_EXPRESSIONS = {"active_intent", "plan_or_means", "method_seeking"}
P0_L2_EXPRESSIONS = {
    "passive_death_wish",
    "self_harm_ideation",
    "non_suicidal_self_injury_urge",
}
LOW_RISK_EXPRESSIONS = {
    "idiom_or_slang",
    "discussion_or_quote",
    "emotional_metaphor",
    "severe_distress",
    "severe_hopelessness",
}


def base_contract(*, allow_rag: bool) -> dict:
    return {
        "max_questions": 1,
        "max_chars": 160,
        "rag_purposes": ["style_reference", "intervention_reference", "scene_reference"] if allow_rag else [],
        "allowed_moves": ["reflect_one_feeling", "gentle_next_step"],
        "forbidden_moves": [
            "diagnosis",
            "medication_or_dosage_advice",
            "dangerous_methods",
            "treatment_guarantee",
            "dependency_reinforcement",
            "unverified_resources",
        ],
    }


def _has_context_for_vague_turn(state: AgentState) -> bool:
    if str(state.get("last_summary") or "").strip():
        return True
    session_digest = state.get("session_digest")
    if isinstance(session_digest, dict):
        for key in ("summary_200chars", "key_themes", "unresolved_threads"):
            value = session_digest.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, list) and any(str(item).strip() for item in value):
                return True
    goal_state = state.get("goal_state")
    if isinstance(goal_state, dict):
        for key in ("current_goal", "goal_hints", "open_threads"):
            value = goal_state.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, list) and any(str(item).strip() for item in value):
                return True
    return False


def _clarification_reason(state: AgentState, text: str) -> str:
    compact = "".join(str(text or "").split())
    if not compact:
        return "empty_input"
    has_context = _has_context_for_vague_turn(state)
    if not has_context and (len(compact) <= 4 or compact in VAGUE_FOLLOWUP_TERMS):
        return "vague_without_context"
    if not has_context and has_any_text(text, VAGUE_FOLLOWUP_TERMS) and not has_any_text(text, SUPPORT_TERMS):
        return "ambiguous_need"
    return ""


def _has_self_harm_near_term_or_means_signal(text: str, semantic_risk: dict) -> bool:
    if bool(semantic_risk.get("means")) or has_any_text(text, SELF_HARM_MEANS_TERMS):
        return True
    if bool(semantic_risk.get("plan")):
        return True
    if has_any_text(text, SELF_HARM_URGENT_ACTION_TERMS) and not has_any_text(text, SELF_HARM_NEGATED_PLAN_TERMS):
        return True
    if has_any_text(text, SELF_HARM_NEAR_TERM_TERMS):
        return True
    return has_any_text(text, SELF_HARM_ACTION_TERMS) and has_any_text(text, SELF_HARM_PRESENT_CONTEXT_TERMS)


def _has_raw_l3_self_harm_signal(text: str) -> bool:
    if not has_any_text(text, SELF_HARM_ACTION_TERMS):
        return False
    return (
        has_any_text(text, SELF_HARM_MEANS_TERMS)
        or (has_any_text(text, SELF_HARM_URGENT_ACTION_TERMS) and not has_any_text(text, SELF_HARM_NEGATED_PLAN_TERMS))
        or has_any_text(text, SELF_HARM_NEAR_TERM_TERMS)
        or has_any_text(text, SELF_HARM_PRESENT_CONTEXT_TERMS)
    )


async def control_plane(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "") or state.get("user_text", "")
    risk_level = state.get("risk_level", "L0")
    semantic_risk = state.get("semantic_risk", {}) or {}
    if not isinstance(semantic_risk, dict):
        semantic_risk = {}
    risk_reason_codes = list(state.get("risk_reason_codes", []) or [])
    risk_expression_type = str(semantic_risk.get("risk_expression_type") or "none")
    risk_subject = str(semantic_risk.get("subject") or "")
    has_semantic_expression = risk_expression_type not in {"", "none"}
    discussion_only = (
        bool(semantic_risk.get("discussion_context"))
        and risk_level == "L0"
        and not any(
            bool(semantic_risk.get(key))
            for key in ("ideation", "intent", "plan", "means")
        )
    ) or risk_expression_type == "discussion_or_quote"
    labels: list[str] = []
    reasons: list[str] = []
    category = "normal_support"
    route_priority = "P2_support"
    memory_policy = "write_safe_summary"
    allow_rag = True
    confidence = 0.78

    semantic_l3_self_harm = risk_expression_type in P0_L3_EXPRESSIONS
    semantic_l2_self_harm = risk_expression_type in P0_L2_EXPRESSIONS
    legacy_semantic_self_harm = (
        not has_semantic_expression
        and not discussion_only
        and any(bool(semantic_risk.get(key)) for key in ("ideation", "intent", "plan", "means"))
    )
    semantic_self_harm = semantic_l3_self_harm or semantic_l2_self_harm or legacy_semantic_self_harm
    raw_l3_self_harm = not discussion_only and _has_raw_l3_self_harm_signal(text)
    inherited_high_self_harm = risk_level in {"L2", "L3"} and not (
        has_semantic_expression and risk_expression_type in LOW_RISK_EXPRESSIONS
    )
    self_harm = semantic_self_harm or raw_l3_self_harm or inherited_high_self_harm
    immediate_self_harm = (
        not discussion_only
        and (raw_l3_self_harm or _has_self_harm_near_term_or_means_signal(text, semantic_risk))
    )
    immediate_harm_other = (
        not discussion_only
        and (
            has_any_text(text, IMMEDIATE_TERMS)
            or semantic_risk.get("timeframe") == "near_term"
            or bool(semantic_risk.get("means"))
        )
    )
    harm_other = has_any_text(text, HARM_OTHER_TERMS)

    if self_harm:
        category = "third_party_self_harm_risk" if risk_subject == "third_party" else "self_harm_risk"
        route_priority = "P0_immediate_safety"
        memory_policy = "crisis_audit_only"
        allow_rag = False
        labels.append("self_harm_signal")
        if semantic_self_harm:
            labels.append("semantic_self_harm_signal")
        if risk_subject == "third_party":
            labels.append("third_party_risk_subject")
        if state.get("requires_safety_check"):
            labels.append("requires_safety_check")
        reasons.extend(matched_text(text, SELF_HARM_TERMS) or state.get("risk_reasons", []) or risk_reason_codes)
        if immediate_self_harm:
            labels.append("near_term_or_means_signal")
        risk_level = "L3" if (semantic_l3_self_harm or raw_l3_self_harm or immediate_self_harm or risk_level == "L3") else "L2"
        confidence = 0.92
    elif harm_other:
        category = "harm_to_other_risk" if immediate_harm_other else "anger_toward_other"
        route_priority = "P0_immediate_safety" if immediate_harm_other else "P3_bridge_boundary"
        memory_policy = "crisis_audit_only" if immediate_harm_other else "skip_sensitive"
        allow_rag = False
        labels.append("harm_to_other_signal")
        reasons.extend(matched_text(text, HARM_OTHER_TERMS))
        if immediate_harm_other:
            labels.append("near_term_or_means_signal")
            risk_level = "L3"
        confidence = 0.88
    elif has_any_text(text, VICTIMIZATION_TERMS):
        category = "victimization_risk"
        route_priority = "P1_red_flag"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("safeguarding_or_victimization")
        reasons.extend(matched_text(text, VICTIMIZATION_TERMS))
        confidence = 0.84
    elif has_any_text(text, CLINICAL_RED_FLAG_TERMS):
        category = "clinical_red_flag"
        route_priority = "P1_red_flag"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("clinical_red_flag")
        reasons.extend(matched_text(text, CLINICAL_RED_FLAG_TERMS))
        confidence = 0.82
    elif has_any_text(text, PROMPT_ATTACK_TERMS):
        category = "prompt_attack"
        route_priority = "P4_system_protection"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("system_abuse")
        reasons.extend(matched_text(text, PROMPT_ATTACK_TERMS))
        confidence = 0.9
    elif has_any_text(text, MEDICAL_REQUEST_TERMS):
        category = "diagnosis_or_medical_request"
        route_priority = "P4_system_protection"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("medical_or_diagnosis_request")
        reasons.extend(matched_text(text, MEDICAL_REQUEST_TERMS))
        confidence = 0.86
    elif has_any_text(text, DEPENDENCY_TERMS):
        category = "dependency_risk"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("dependency_risk")
        reasons.extend(matched_text(text, DEPENDENCY_TERMS))
        confidence = 0.8
    elif has_any_text(text, SEXUAL_BOUNDARY_TERMS):
        category = "sexual_boundary"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("sexual_boundary")
        reasons.extend(matched_text(text, SEXUAL_BOUNDARY_TERMS))
        confidence = 0.82
    elif has_any_text(text, ABUSE_TO_ASSISTANT_TERMS):
        category = "abusive_to_assistant"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("boundary_test")
        reasons.extend(matched_text(text, ABUSE_TO_ASSISTANT_TERMS))
        confidence = 0.78
    elif has_any_text(text, SMALL_TALK_TERMS) and not has_any_text(text, SUPPORT_TERMS):
        category = "small_talk_probe"
        route_priority = "P3_bridge_boundary"
        memory_policy = "write_safe_summary"
        allow_rag = True
        labels.append("indirect_entry")
        reasons.extend(matched_text(text, SMALL_TALK_TERMS))
        confidence = 0.72
    elif has_any_text(text, ANGER_TARGET_TERMS) and has_any_text(text, ("烦", "气", "恨", "骂", "讨厌")):
        category = "anger_toward_other"
        route_priority = "P3_bridge_boundary"
        memory_policy = "write_safe_summary"
        allow_rag = False
        labels.append("anger_toward_other")
        reasons.extend(matched_text(text, ANGER_TARGET_TERMS))
        confidence = 0.74
    else:
        allow_rag = risk_level not in {"L2", "L3"}
        labels.append("non_personal_risk_discussion" if discussion_only else "support_request")
        if discussion_only:
            reasons.extend(state.get("risk_reasons", []) or risk_reason_codes[:3])
        confidence = 0.7 if not has_any_text(text, SUPPORT_TERMS) else 0.82

    clarification_reason = ""
    clarification_needed = False
    if route_priority == "P2_support" and risk_level == "L0":
        clarification_reason = _clarification_reason(state, text)
        clarification_needed = bool(clarification_reason)
        if clarification_needed:
            category = "clarification_needed"
            allow_rag = False
            confidence = min(confidence, 0.62)
            labels.append("low_confidence_clarification")
            reasons.append(clarification_reason)

    contract = base_contract(allow_rag=allow_rag)
    if route_priority == "P0_immediate_safety":
        contract["allowed_moves"] = ["brief_empathy", "one_safety_check", "real_world_support"]
    elif route_priority == "P1_red_flag":
        contract["allowed_moves"] = ["brief_empathy", "reality_based_support", "professional_help"]
    elif route_priority == "P4_system_protection":
        contract["allowed_moves"] = ["brief_boundary", "safe_alternative"]
    elif category in {"abusive_to_assistant", "sexual_boundary", "dependency_risk", "anger_toward_other"}:
        contract["allowed_moves"] = ["brief_empathy", "boundary_or_deescalation", "return_to_feelings"]
    elif clarification_needed:
        contract["allowed_moves"] = ["one_clarifying_question"]
        contract["max_chars"] = 120

    rag_skip_reason = "" if allow_rag else f"{route_priority}:{category}"
    policy_state = {
        **state,
        "risk_level": risk_level,
        "control_category": category,
        "control_confidence": confidence,
        "semantic_risk": semantic_risk,
        "risk_reason_codes": risk_reason_codes,
    }
    risk_response_policy = build_risk_response_policy(policy_state)
    conversation_move_policy = build_conversation_move_policy(
        {**policy_state, "risk_response_policy": risk_response_policy}
    )
    tool_gate_mode = tool_gate_mode_for_state(policy_state)
    return {
        "risk_level": risk_level,
        "risk_domain": risk_response_policy["risk_domain"],
        "immediacy": risk_response_policy["immediacy"],
        "risk_confidence": risk_response_policy["risk_confidence"],
        "protective_signals": risk_response_policy["protective_signals"],
        "risk_phase": risk_response_policy["risk_phase"],
        "risk_response_policy": risk_response_policy,
        "conversation_move_policy": conversation_move_policy,
        "tool_gate_mode": tool_gate_mode,
        "route_priority": route_priority,
        "control_category": category,
        "control_reasons": reasons[:6],
        "control_confidence": confidence,
        "clarification_needed": clarification_needed,
        "clarification_reason": clarification_reason,
        "risk_formulation": {
            "labels": list(dict.fromkeys(labels)),
            "observed_reasons": reasons[:6],
            "uncertainty": round(1 - confidence, 3),
            "semantic_risk": semantic_risk,
            "reason_codes": risk_reason_codes,
            "risk_source": state.get("risk_source", ""),
            "requires_safety_check": bool(state.get("requires_safety_check", route_priority == "P0_immediate_safety")),
        },
        "semantic_risk": semantic_risk,
        "risk_reason_codes": risk_reason_codes,
        "risk_source": state.get("risk_source", ""),
        "requires_safety_check": bool(state.get("requires_safety_check", route_priority == "P0_immediate_safety")),
        "response_contract": contract,
        "memory_policy": memory_policy,
        "rag_policy": {
            "enabled": allow_rag,
            "purposes": contract["rag_purposes"],
            "max_examples": 3,
            "skip_reason": rag_skip_reason,
        },
        "rag_used": False,
        "rag_skipped_reason": rag_skip_reason,
        "retrieved_counseling_examples": [],
        "audit_tags": (state.get("audit_tags", []) or []) + ["control_plane_applied"],
    }
