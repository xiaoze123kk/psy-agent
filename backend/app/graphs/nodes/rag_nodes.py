from __future__ import annotations

from app.graphs.nodes.common import AgentState
from app.services.counseling_vector_service import retrieve_counseling_examples


def response_mode_for_state(state: AgentState) -> str:
    intent = state.get("intent", "other")
    if intent == "soothe":
        return "soothe"
    if intent == "light_counseling":
        return "counseling"
    if intent == "vent":
        return "vent"
    return "companion"


def example_hit_to_dict(example: object) -> dict:
    if isinstance(example, dict):
        return dict(example)
    return {
        "content": str(getattr(example, "content", "") or ""),
        "source_key": str(getattr(example, "source_key", "") or ""),
        "source_name": str(getattr(example, "source_name", "") or ""),
        "mode": str(getattr(example, "mode", "") or ""),
        "source_url": str(getattr(example, "source_url", "") or ""),
        "license": str(getattr(example, "license", "") or ""),
        "score": float(getattr(example, "score", 0.0) or 0.0),
        "chunk_id": str(getattr(example, "chunk_id", "") or ""),
        "scenario_tags": list(getattr(example, "scenario_tags", None) or []),
        "intervention_tags": list(getattr(example, "intervention_tags", None) or []),
        "style_tags": list(getattr(example, "style_tags", None) or []),
    }


async def example_retriever(state: AgentState) -> AgentState:
    from app.services.counseling_vector_service import counseling_rag_allowed

    allowed, reason = counseling_rag_allowed(state)
    if not allowed:
        return {
            "retrieved_counseling_examples": [],
            "rag_used": False,
            "rag_skipped_reason": reason,
            "audit_tags": (state.get("audit_tags", []) or []) + ["rag_skipped"],
        }

    mode = response_mode_for_state(state)
    examples = await retrieve_counseling_examples(state, mode=mode, limit=3)
    serialized = [example_hit_to_dict(example) for example in examples]
    return {
        "retrieved_counseling_examples": serialized,
        "rag_used": bool(serialized),
        "rag_skipped_reason": "" if serialized else "no_safe_examples",
        "audit_tags": (state.get("audit_tags", []) or []) + (["rag_used"] if serialized else ["rag_empty"]),
    }
