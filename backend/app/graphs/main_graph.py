from langgraph.graph import END, START, StateGraph

from app.graphs.nodes.control_nodes import control_plane
from app.graphs.nodes.input_nodes import load_user_profile, normalize_input
from app.graphs.nodes.memory_nodes import memory_candidate_extract, skip_memory, summarize_turn, write_memory
from app.graphs.nodes.rag_nodes import example_retriever
from app.graphs.nodes.response_nodes import (
    boundary_response,
    clinical_red_flag_response,
    companion_response,
    crisis_response,
    counseling_response,
    soothing_response,
)
from app.graphs.nodes.risk_nodes import intent_classifier, risk_classifier
from app.graphs.nodes.validator_nodes import response_validator
from app.graphs.routing import route_by_control, route_by_intent, route_memory_write
from app.graphs.state import AgentState


def build_main_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("normalize_input", normalize_input)
    workflow.add_node("load_user_profile", load_user_profile)
    workflow.add_node("risk_classifier", risk_classifier)
    workflow.add_node("control_plane", control_plane)
    workflow.add_node("intent_classifier", intent_classifier)
    workflow.add_node("example_retriever", example_retriever)

    workflow.add_node("boundary_response", boundary_response)
    workflow.add_node("clinical_red_flag_response", clinical_red_flag_response)
    workflow.add_node("companion_response", companion_response)
    workflow.add_node("soothing_response", soothing_response)
    workflow.add_node("counseling_response", counseling_response)
    workflow.add_node("crisis_response", crisis_response)
    workflow.add_node("response_validator", response_validator)

    workflow.add_node("summarize_turn", summarize_turn)
    workflow.add_node("memory_candidate_extract", memory_candidate_extract)
    workflow.add_node("write_memory", write_memory)
    workflow.add_node("skip_memory", skip_memory)

    workflow.add_edge(START, "normalize_input")
    workflow.add_edge("normalize_input", "load_user_profile")
    workflow.add_edge("load_user_profile", "risk_classifier")
    workflow.add_edge("risk_classifier", "control_plane")

    workflow.add_conditional_edges(
        "control_plane",
        route_by_control,
        {
            "crisis_response": "crisis_response",
            "clinical_red_flag_response": "clinical_red_flag_response",
            "boundary_response": "boundary_response",
            "intent_classifier": "intent_classifier",
        },
    )

    workflow.add_edge("intent_classifier", "example_retriever")

    workflow.add_conditional_edges(
        "example_retriever",
        route_by_intent,
        {
            "soothing_response": "soothing_response",
            "counseling_response": "counseling_response",
            "companion_response": "companion_response",
        },
    )

    workflow.add_edge("boundary_response", "response_validator")
    workflow.add_edge("clinical_red_flag_response", "response_validator")
    workflow.add_edge("companion_response", "response_validator")
    workflow.add_edge("soothing_response", "response_validator")
    workflow.add_edge("counseling_response", "response_validator")
    workflow.add_edge("crisis_response", "response_validator")
    workflow.add_edge("response_validator", "summarize_turn")

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
