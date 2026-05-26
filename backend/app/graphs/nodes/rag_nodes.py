from __future__ import annotations

import asyncio
import math

from app.core.config import settings
from app.graphs.nodes.common import AgentState
from app.services.counseling_vector_service import retrieve_counseling_examples_with_trace


def response_mode_for_state(state: AgentState) -> str:
    intent = state.get("intent", "other")
    if intent == "soothe":
        return "soothe"
    if intent == "light_counseling":
        return "counseling"
    if intent == "vent":
        return "vent"
    return "companion"


def coerce_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return []


def effective_rag_timeout_seconds(rag_timeout_seconds: float, chat_timeout_seconds: float) -> float:
    rag_timeout = max(float(rag_timeout_seconds), 0.001)
    chat_timeout = max(float(chat_timeout_seconds), 0.001)
    response_budget_seconds = 30.0
    return min(rag_timeout, max(chat_timeout - response_budget_seconds, 0.001))


def example_hit_to_dict(example: object) -> dict:
    if isinstance(example, dict):
        serialized = dict(example)
        if "rerank_score" in serialized or "rerank_reasons" in serialized:
            serialized["rerank_score"] = coerce_optional_float(serialized.get("rerank_score"))
            serialized["rerank_reasons"] = coerce_string_list(serialized.get("rerank_reasons"))
        return serialized
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
        "chunk_type": str(getattr(example, "chunk_type", "") or "turn_pair"),
        "original_external_id": str(getattr(example, "original_external_id", "") or ""),
        "phase": str(getattr(example, "phase", "") or ""),
        "display_text": str(getattr(example, "display_text", "") or ""),
        "process_quality_score": getattr(example, "process_quality_score", None),
        "rerank_score": coerce_optional_float(getattr(example, "rerank_score", None)),
        "rerank_reasons": coerce_string_list(getattr(example, "rerank_reasons", None)),
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
    timeout_seconds = effective_rag_timeout_seconds(
        settings.rag_retrieval_timeout_seconds,
        settings.chat_turn_timeout_seconds,
    )
    try:
        retrieval = await asyncio.wait_for(
            retrieve_counseling_examples_with_trace(
                state,
                mode=mode,
                limit=3,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        timeout_ms = max(1, int(timeout_seconds * 1000))
        return {
            "retrieved_counseling_examples": [],
            "rag_used": False,
            "rag_skipped_reason": "rag_timeout",
            "rag_trace_summary": {
                "status": "timeout",
                "phase": "retrieval",
                "hit_count": 0,
                "timeout_ms": timeout_ms,
                "total_duration_ms": timeout_ms,
            },
            "audit_tags": (state.get("audit_tags", []) or []) + ["rag_timeout"],
        }
    except Exception as exc:
        return {
            "retrieved_counseling_examples": [],
            "rag_used": False,
            "rag_skipped_reason": "rag_error",
            "rag_trace_summary": {
                "status": "error",
                "phase": "retrieval",
                "hit_count": 0,
                "error": type(exc).__name__,
            },
            "audit_tags": (state.get("audit_tags", []) or []) + ["rag_error"],
        }

    examples = retrieval.examples
    rag_trace_summary = retrieval.trace
    serialized = [example_hit_to_dict(example) for example in examples]
    skipped_reason = "" if serialized else str(rag_trace_summary.get("skipped_reason") or "no_safe_examples")
    audit_tag = "rag_used" if serialized else ("rag_timeout" if skipped_reason == "rag_timeout" else "rag_empty")
    return {
        "retrieved_counseling_examples": serialized,
        "rag_used": bool(serialized),
        "rag_skipped_reason": skipped_reason,
        "rag_trace_summary": rag_trace_summary,
        "audit_tags": (state.get("audit_tags", []) or []) + [audit_tag],
    }
