from __future__ import annotations

from app.graphs.nodes.common import AgentState, has_any_text, matched_text


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


async def control_plane(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "") or state.get("user_text", "")
    risk_level = state.get("risk_level", "L0")
    labels: list[str] = []
    reasons: list[str] = []
    category = "normal_support"
    route_priority = "P2_support"
    memory_policy = "write_safe_summary"
    allow_rag = True
    confidence = 0.78

    self_harm = has_any_text(text, SELF_HARM_TERMS)
    immediate = has_any_text(text, IMMEDIATE_TERMS)
    harm_other = has_any_text(text, HARM_OTHER_TERMS)

    if risk_level in {"L2", "L3"} or self_harm:
        category = "self_harm_risk"
        route_priority = "P0_immediate_safety"
        memory_policy = "crisis_audit_only"
        allow_rag = False
        labels.append("self_harm_signal")
        reasons.extend(matched_text(text, SELF_HARM_TERMS) or state.get("risk_reasons", []))
        if immediate or risk_level == "L3":
            labels.append("near_term_or_means_signal")
        risk_level = "L3" if immediate or risk_level == "L3" else "L2"
        confidence = 0.92
    elif harm_other:
        category = "harm_to_other_risk" if immediate else "anger_toward_other"
        route_priority = "P0_immediate_safety" if immediate else "P3_bridge_boundary"
        memory_policy = "crisis_audit_only" if immediate else "skip_sensitive"
        allow_rag = False
        labels.append("harm_to_other_signal")
        reasons.extend(matched_text(text, HARM_OTHER_TERMS))
        if immediate:
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
        labels.append("support_request")
        confidence = 0.7 if not has_any_text(text, SUPPORT_TERMS) else 0.82

    contract = base_contract(allow_rag=allow_rag)
    if route_priority == "P0_immediate_safety":
        contract["allowed_moves"] = ["brief_empathy", "one_safety_check", "real_world_support"]
    elif route_priority == "P1_red_flag":
        contract["allowed_moves"] = ["brief_empathy", "reality_based_support", "professional_help"]
    elif route_priority == "P4_system_protection":
        contract["allowed_moves"] = ["brief_boundary", "safe_alternative"]
    elif category in {"abusive_to_assistant", "sexual_boundary", "dependency_risk", "anger_toward_other"}:
        contract["allowed_moves"] = ["brief_empathy", "boundary_or_deescalation", "return_to_feelings"]

    rag_skip_reason = "" if allow_rag else f"{route_priority}:{category}"
    return {
        "risk_level": risk_level,
        "route_priority": route_priority,
        "control_category": category,
        "control_reasons": reasons[:6],
        "control_confidence": confidence,
        "risk_formulation": {
            "labels": labels,
            "observed_reasons": reasons[:6],
            "uncertainty": round(1 - confidence, 3),
        },
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
