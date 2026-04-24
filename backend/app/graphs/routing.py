from app.graphs.state import AgentState


def route_by_risk(state: AgentState) -> str:
    if state.get("risk_level") in {"L2", "L3"}:
        return "crisis_response"
    return "intent_classifier"


def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent", "other")
    if intent == "knowledge_qa":
        return "knowledge_retrieve"
    if intent == "test_interpretation":
        return "test_context"
    if intent == "anime_match":
        return "anime_context"
    if intent == "soothe":
        return "soothing_response"
    if intent == "light_counseling":
        return "counseling_response"
    return "companion_response"


def route_memory_write(state: AgentState) -> str:
    if state.get("memory_mode") == "off":
        return "skip_memory"
    if not state.get("memory_candidates"):
        return "skip_memory"
    return "write_memory"
