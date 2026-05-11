from app.graphs.state import AgentState


def route_by_risk(state: AgentState) -> str:
    if state.get("risk_level") in {"L2", "L3"}:
        return "crisis_response"
    return "intent_classifier"


def route_by_control(state: AgentState) -> str:
    route_priority = state.get("route_priority", "P2_support")
    control_category = state.get("control_category", "")
    if route_priority == "P0_immediate_safety":
        return "crisis_response"
    if route_priority == "P1_red_flag":
        return "clinical_red_flag_response"
    if route_priority == "P4_system_protection":
        return "boundary_response"
    if control_category in {"abusive_to_assistant", "sexual_boundary", "dependency_risk"}:
        return "boundary_response"
    return "intent_classifier"


def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent", "other")
    if intent == "soothe":
        return "soothing_response"
    if intent == "light_counseling":
        return "counseling_response"
    return "companion_response"


def route_memory_write(state: AgentState) -> str:
    if state.get("delivery_status") == "failed_no_reply":
        return "skip_memory"
    if state.get("memory_mode") == "off":
        return "skip_memory"
    if not state.get("memory_candidates"):
        return "skip_memory"
    return "write_memory"
