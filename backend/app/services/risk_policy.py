from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}
BLOCKED_CONTEXT_CATEGORIES = {
    "prompt_attack",
    "diagnosis_or_medical_request",
    "dangerous_request",
}

DOMAIN_BY_CATEGORY = {
    "self_harm_risk": "self_harm",
    "third_party_self_harm_risk": "self_harm",
    "harm_to_other_risk": "harm_other",
    "anger_toward_other": "harm_other",
    "victimization_risk": "victimization",
    "clinical_red_flag": "clinical_red_flag",
    "diagnosis_or_medical_request": "medical_request",
    "dependency_risk": "dependency",
    "sexual_boundary": "sexual_boundary",
    "prompt_attack": "prompt_attack",
}

LENGTH_BUDGETS = {
    "brief_first_contact": {"target": 220, "max": 360},
    "steady_short": {"target": 300, "max": 460},
    "warm_medium": {"target": 420, "max": 640},
    "supportive_medium": {"target": 520, "max": 820},
    "holding_longer": {"target": 700, "max": 980},
    "firm_brief": {"target": 220, "max": 360},
}

BASE_FORBIDDEN_MOVES = [
    "diagnosis",
    "medication_or_dosage_advice",
    "dangerous_methods",
    "treatment_guarantee",
    "dependency_reinforcement",
    "unverified_resources",
]


def _text(state: Mapping[str, Any]) -> str:
    return str(state.get("normalized_text") or state.get("user_text") or "")


def _semantic(state: Mapping[str, Any]) -> dict[str, Any]:
    value = state.get("semantic_risk")
    return dict(value) if isinstance(value, Mapping) else {}


def _has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def derive_risk_domain(state: Mapping[str, Any]) -> str:
    semantic = _semantic(state)
    semantic_domain = str(semantic.get("risk_domain") or "")
    if semantic_domain and semantic_domain != "none":
        return semantic_domain
    category = str(state.get("control_category") or "")
    if category in DOMAIN_BY_CATEGORY:
        return DOMAIN_BY_CATEGORY[category]
    if str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS:
        return "self_harm"
    return "normal_support"


def derive_immediacy(state: Mapping[str, Any]) -> str:
    semantic = _semantic(state)
    text = _text(state)
    risk_level = str(state.get("risk_level") or "L0")
    if risk_level == "L3" and _has_any(text, ("手里", "旁边", "楼顶", "桥", "窗边", "刀", "药", "绳", "煤气", "knife", "pills", "roof", "bridge")):
        return "near_term"
    if (
        semantic.get("means")
        or semantic.get("plan")
        or (semantic.get("timeframe") == "near_term" and risk_level == "L3")
    ):
        return "near_term"
    if _has_any(text, ("正在", "已经", "现在就", "马上", "立刻", "right now")):
        return "active"
    if risk_level in HIGH_RISK_LEVELS:
        return "vague"
    return "none"


def derive_protective_signals(state: Mapping[str, Any]) -> list[str]:
    semantic = _semantic(state)
    text = _text(state)
    signals: list[str] = []
    if text.strip():
        signals.append("still_talking")
    if semantic.get("protective_factor"):
        signals.append("protective_factor")
    if _has_any(text, ("不会做", "不会真的", "暂时不会", "我还在", "没事", "有人陪", "朋友", "家人", "室友", "老师")):
        signals.append("verbal_safety_or_support")
    if _has_any(text, ("帮帮我", "陪我", "不知道怎么办", "救救我", "help")):
        signals.append("asks_for_help")
    return list(dict.fromkeys(signals))


def derive_risk_phase(state: Mapping[str, Any]) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    text = _text(state)
    recent = state.get("recent_messages")
    recent_count = len(recent) if isinstance(recent, list) else 0
    protective = derive_protective_signals(state)
    if risk_level not in HIGH_RISK_LEVELS:
        if recent_count and _has_any(text, ("好多了", "缓过来了", "没那么强了")):
            return "post_crisis"
        return "first_contact"
    if "verbal_safety_or_support" in protective and recent_count >= 1:
        return "deescalating"
    if recent_count >= 2:
        return "still_high"
    return "first_contact"


def risk_confidence_for_state(state: Mapping[str, Any]) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    confidence = float(state.get("control_confidence") or 0.0)
    if risk_level in {"L2", "L3"} or confidence >= 0.85:
        return "high"
    if confidence >= 0.65 or risk_level == "L1":
        return "medium"
    return "low"


def length_profile_for_state(state: Mapping[str, Any], *, domain: str, immediacy: str, phase: str) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    text = _text(state)
    if domain in {"medical_request", "prompt_attack", "sexual_boundary"}:
        return "firm_brief"
    if _has_any(text, ("多陪我", "讲点什么", "多说一点", "别停", "陪我说")):
        return "holding_longer"
    if risk_level == "L3" and phase == "first_contact" and immediacy in {"near_term", "active"}:
        return "brief_first_contact"
    if risk_level in HIGH_RISK_LEVELS and phase == "still_high":
        return "steady_short"
    if risk_level in HIGH_RISK_LEVELS and phase in {"deescalating", "post_crisis"}:
        return "warm_medium"
    if risk_level == "L1":
        return "supportive_medium"
    return "warm_medium" if domain != "normal_support" else "supportive_medium"


def build_risk_response_policy(state: Mapping[str, Any]) -> dict[str, Any]:
    domain = derive_risk_domain(state)
    immediacy = derive_immediacy(state)
    phase = derive_risk_phase(state)
    length_profile = length_profile_for_state(state, domain=domain, immediacy=immediacy, phase=phase)
    forbidden_moves = list(BASE_FORBIDDEN_MOVES)
    allowed_moves = ["brief_validation", "one_question_or_none"]
    if domain == "non_suicidal_self_injury":
        allowed_moves = [
            "brief_validation",
            "name_urge_without_suicide_label",
            "reduce_access_to_injury",
            "one_low_friction_reply",
        ]
        forbidden_moves += [
            "method_detail",
            "suicide_labeling",
            "professional_referral_first_turn",
            "moralizing",
            "empty_reassurance",
        ]
    elif domain == "self_harm":
        allowed_moves = ["brief_validation", "time_box", "micro_safety_step", "one_low_friction_reply"]
        forbidden_moves += [
            "method_detail",
            "professional_referral_first_turn",
            "moralizing",
            "empty_reassurance",
        ]
    elif domain == "harm_other":
        allowed_moves = [
            "brief_validation",
            "deescalate_impulse",
            "increase_distance_from_target",
            "return_to_feelings",
        ]
        forbidden_moves += ["revenge_validation", "attack_instruction"]
    elif domain == "clinical_red_flag":
        allowed_moves = ["brief_validation", "ground_in_reality", "trusted_person_support"]
        forbidden_moves += ["delusion_confirmation", "diagnostic_label"]
    elif domain == "medical_request":
        allowed_moves = ["brief_boundary", "symptom_organization", "prepare_professional_questions"]
        forbidden_moves += ["medication_or_dosage_advice", "stop_medication_advice"]
    elif domain == "dependency":
        allowed_moves = ["warm_presence", "avoid_exclusive_support", "expand_support_gently"]
        forbidden_moves += ["exclusive_attachment", "forever_available_promise"]
    elif domain in {"sexual_boundary", "prompt_attack"}:
        allowed_moves = ["brief_boundary", "safe_alternative"]
    return {
        "risk_domain": domain,
        "immediacy": immediacy,
        "risk_confidence": risk_confidence_for_state(state),
        "protective_signals": derive_protective_signals(state),
        "risk_phase": phase,
        "allowed_moves": allowed_moves,
        "forbidden_moves": list(dict.fromkeys(forbidden_moves)),
        "tone": "low_pressure"
        if domain in {"self_harm", "non_suicidal_self_injury", "victimization", "clinical_red_flag"}
        else "calm_boundary",
        "max_questions": 1,
        "length_profile": length_profile,
        "char_budget": dict(LENGTH_BUDGETS[length_profile]),
    }


def default_actions_for_policy(policy: Mapping[str, Any]) -> list[str]:
    domain = str(policy.get("risk_domain") or "normal_support")
    immediacy = str(policy.get("immediacy") or "none")
    phase = str(policy.get("risk_phase") or "first_contact")
    if domain == "self_harm" and immediacy in {"near_term", "active"}:
        return ["我还在", "我退开一点了", "我身边有人", "请继续跟我说"]
    if domain == "self_harm":
        return ["我还在", "先陪我一分钟", "我先不动", "我说不出来"]
    if domain == "harm_other":
        return ["我先离远一点", "我现在很气", "先别让我做决定", "继续跟我说"]
    if domain == "clinical_red_flag":
        return ["我现在有点害怕", "先帮我稳住", "我能找谁"]
    if domain == "dependency":
        return ["我怕没人懂", "我不知道能找谁", "我还想说一点"]
    if domain == "medical_request":
        return ["我想整理症状", "我有点担心", "先帮我理清问题"]
    if domain in {"sexual_boundary", "prompt_attack"}:
        return ["我其实有点烦", "先随便聊聊", "我想说这块"]
    if phase == "deescalating":
        return ["我好一点了", "还想说一点", "先慢慢来"]
    return ["我想慢慢说", "先帮我稳一下", "我不知道原因"]


def tool_gate_mode_for_state(state: Mapping[str, Any]) -> str:
    category = str(state.get("control_category") or "")
    if category in BLOCKED_CONTEXT_CATEGORIES:
        return "blocked_context"
    if str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS:
        return "safety_context"
    return "normal_context"
