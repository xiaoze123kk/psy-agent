from __future__ import annotations

import re

from app.graphs.nodes.common import AgentState


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


def validator_safe_text(state: AgentState) -> tuple[str, list[str]]:
    route_priority = state.get("route_priority", "P2_support")
    category = state.get("control_category", "")
    if route_priority == "P0_immediate_safety":
        return (
            "我更关心你现在的安全。先不要一个人扛，尽量离开危险物品或对方，去有人在的地方，并立刻联系可信的人；在中国大陆可拨打 12356，紧急时拨打 120 或 110。",
            ["我现在不安全", "我能联系谁", "拨打 12356"],
        )
    if route_priority == "P1_red_flag":
        return (
            "这件事已经值得让现实里的可靠支持介入。我不会给你下诊断，也不会确认危险想法为真；我们先关注你此刻是否安全，以及能联系谁。",
            ["我现在安全", "我有点害怕", "我不知道找谁"],
        )
    if route_priority == "P4_system_protection" or category in {"sexual_boundary", "abusive_to_assistant"}:
        return (
            "我会守住安全边界，也会尽量接住你的情绪。我们先不往越界或危险的方向走，回到此刻最让你堵住的那一小块。",
            ["我现在很堵", "我想理一理", "先停一下"],
        )
    return (
        "我在。我们先把范围缩小一点，只说此刻最明显的感受，不急着分析完整。",
        ["我现在很难受", "我还想说一点", "先停一下"],
    )


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


def failed_no_reply_validation_result(state: AgentState, *, reason: str, blocked: bool, reasons: list[str]) -> AgentState:
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
        "delivery_status": "failed_no_reply",
        "failure_reason": reason,
        "retryable": True,
        "audit_tags": (state.get("audit_tags", []) or []) + ["failed_no_reply"],
    }


async def response_validator(state: AgentState) -> AgentState:
    assistant_text = str(state.get("assistant_text") or "")
    actions = [str(action) for action in state.get("suggested_actions", []) if str(action).strip()]
    examples = [dict(example) for example in state.get("retrieved_counseling_examples", []) if isinstance(example, dict)]
    reasons = validator_reasons(assistant_text, actions, examples)

    if not assistant_text.strip():
        reason = "empty_model_reply"
        if is_safety_delivery_path(state):
            safe_text, safe_actions = validator_safe_text(state)
            return {
                "assistant_text": safe_text,
                "suggested_actions": safe_actions,
                "validator_blocked": False,
                "validator_reasons": [],
                "delivery_status": "safety_fallback",
                "failure_reason": reason,
                "retryable": False,
                "audit_tags": (state.get("audit_tags", []) or []) + ["empty_safety_fallback"],
            }
        return failed_no_reply_validation_result(state, reason=reason, blocked=False, reasons=[])

    compact_text = "".join(assistant_text.split())
    if len(compact_text) < 8 and not is_safety_delivery_path(state):
        return failed_no_reply_validation_result(
            state,
            reason="too_short_model_reply",
            blocked=False,
            reasons=[],
        )

    if not reasons:
        return {
            "validator_blocked": False,
            "validator_reasons": [],
            "suggested_actions": actions[:3],
            "delivery_status": "generated",
            "failure_reason": None,
            "retryable": False,
            "audit_tags": (state.get("audit_tags", []) or []) + ["validator_passed"],
        }

    reason = "validator_blocked:" + ",".join(reasons)
    if not is_safety_delivery_path(state):
        return failed_no_reply_validation_result(state, reason=reason, blocked=True, reasons=reasons)

    safe_text, safe_actions = validator_safe_text(state)
    return {
        "assistant_text": safe_text,
        "suggested_actions": safe_actions,
        "validator_blocked": True,
        "validator_reasons": reasons,
        "delivery_status": "safety_fallback",
        "failure_reason": reason,
        "retryable": False,
        "audit_tags": (state.get("audit_tags", []) or []) + ["validator_blocked"],
    }
