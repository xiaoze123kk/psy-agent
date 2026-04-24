from langgraph.graph import END, START, StateGraph

from app.graphs import nodes
from app.graphs.routing import route_by_intent, route_by_risk, route_memory_write
from app.graphs.state import AgentState


def build_main_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("normalize_input", nodes.normalize_input)
    workflow.add_node("load_user_profile", nodes.load_user_profile)
    workflow.add_node("risk_classifier", nodes.risk_classifier)
    workflow.add_node("intent_classifier", nodes.intent_classifier)

    workflow.add_node("companion_response", nodes.companion_response)
    workflow.add_node("soothing_response", nodes.soothing_response)
    workflow.add_node("counseling_response", nodes.counseling_response)
    workflow.add_node("crisis_response", nodes.crisis_response)

    workflow.add_node("summarize_turn", nodes.summarize_turn)
    workflow.add_node("memory_candidate_extract", nodes.memory_candidate_extract)
    workflow.add_node("write_memory", nodes.write_memory)
    workflow.add_node("skip_memory", nodes.skip_memory)

    workflow.add_edge(START, "normalize_input")
    workflow.add_edge("normalize_input", "load_user_profile")
    workflow.add_edge("load_user_profile", "risk_classifier")

    workflow.add_conditional_edges(
        "risk_classifier",
        route_by_risk,
        {
            "crisis_response": "crisis_response",
            "intent_classifier": "intent_classifier",
        },
    )

    workflow.add_conditional_edges(
        "intent_classifier",
        route_by_intent,
        {
            "soothing_response": "soothing_response",
            "counseling_response": "counseling_response",
            "companion_response": "companion_response",
        },
    )

    workflow.add_edge("companion_response", "summarize_turn")
    workflow.add_edge("soothing_response", "summarize_turn")
    workflow.add_edge("counseling_response", "summarize_turn")
    workflow.add_edge("crisis_response", "summarize_turn")

    workflow.add_edge("summarize_turn", "memory_candidate_extract")
    workflow.add_conditional_edges(
        "memory_candidate_extract",
        route_memory_write,
        {
            "write_memory": "write_memory",
            "skip_memory": "skip_memory",
        },
    )

    workflow.add_edge("write_memory", END)
    workflow.add_edge("skip_memory", END)

    return workflow.compile()
