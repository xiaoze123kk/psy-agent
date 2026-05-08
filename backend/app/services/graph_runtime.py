from app.graphs.main_graph import build_main_graph


def _memory_references(memories: list[dict] | None, risk_level: str) -> list[dict]:
    if risk_level in {"L2", "L3"}:
        return []
    references = []
    for memory in memories or []:
        if memory.get("visibility") != "user_visible":
            continue
        content = str(memory.get("content", "")).strip()
        if not content:
            continue
        references.append(
            {
                "memory_id": str(memory.get("id", "")),
                "memory_type": str(memory.get("memory_type", "")),
                "title": str(memory.get("title", "") or ""),
                "content": content,
                "score": float(memory.get("score", 0.0) or 0.0),
                "why_selected": str(memory.get("why_selected", "") or ""),
                "freshness_warning": str(memory.get("freshness_warning", "") or ""),
            }
        )
    return references


def _response_mode_for_intent(intent: str) -> str:
    if intent == "soothe":
        return "soothe"
    if intent == "light_counseling":
        return "counseling"
    if intent == "vent":
        return "vent"
    return "companion"


def _counseling_references(examples: list[object] | None, risk_level: str) -> list[dict]:
    if risk_level in {"L2", "L3"}:
        return []
    references: list[dict] = []
    for example in examples or []:
        if isinstance(example, dict):
            content = str(example.get("content", "") or "").strip()
            source_key = str(example.get("source_key", "") or "")
            source_name = str(example.get("source_name", "") or "")
            mode = str(example.get("mode", "") or "")
            score = float(example.get("score", 0.0) or 0.0)
            chunk_id = str(example.get("chunk_id", "") or "")
        else:
            content = str(getattr(example, "content", "") or "").strip()
            source_key = str(getattr(example, "source_key", "") or "")
            source_name = str(getattr(example, "source_name", "") or "")
            mode = str(getattr(example, "mode", "") or "")
            score = float(getattr(example, "score", 0.0) or 0.0)
            chunk_id = str(getattr(example, "chunk_id", "") or "")
        if not content:
            continue
        references.append(
            {
                "chunk_id": chunk_id,
                "source_key": source_key,
                "source_name": source_name,
                "mode": mode,
                "score": score,
                "content": content,
            }
        )
    return references


class GraphRuntime:
    _compiled_graph = None

    def __init__(self) -> None:
        if GraphRuntime._compiled_graph is None:
            GraphRuntime._compiled_graph = build_main_graph()
        self.graph = GraphRuntime._compiled_graph

    async def invoke_turn(
        self,
        thread_id: str,
        user_id: str,
        content: str,
        input_type: str = "text",
        user_mode: str = "adult",
        recent_messages: list[dict] | None = None,
        last_summary: str | None = None,
        memory_mode: str = "summary_only",
        companion_style: str = "gentle",
        nickname: str | None = None,
        retrieved_memories: list[dict] | None = None,
        memory_index: list[dict] | None = None,
    ) -> dict[str, object]:
        input_state = {
            "thread_id": thread_id,
            "user_id": user_id,
            "user_text": content,
            "input_type": input_type,
            "user_mode": user_mode,
            "recent_messages": recent_messages or [],
            "last_summary": last_summary or "",
            "memory_mode": memory_mode,
            "profile": {
                "user_mode": user_mode,
                "nickname": nickname or "user",
            },
            "companion_preferences": {
                "style": companion_style,
                "question_tolerance": "low" if user_mode == "teen" else "medium",
            },
            "memory_index": memory_index or [],
            "retrieved_memories": retrieved_memories or [],
        }
        result = await self.graph.ainvoke(
            input_state,
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": user_id,
                }
            },
        )

        risk_level = result.get("risk_level", "L0")
        delivery_status = str(result.get("delivery_status") or "")
        assistant_text = str(result.get("assistant_text", "") or "")
        if not delivery_status:
            delivery_status = "generated" if assistant_text.strip() else "failed_no_reply"
        if delivery_status == "failed_no_reply":
            assistant_text = ""
        retrieved_examples = result.get("retrieved_counseling_examples", [])
        referenced_memories = (
            []
            if delivery_status != "generated"
            else _memory_references(retrieved_memories, str(risk_level))
        )
        referenced_examples = (
            []
            if delivery_status != "generated"
            else _counseling_references(retrieved_examples, str(risk_level))
        )
        return {
            "assistant_text": assistant_text,
            "risk_level": risk_level,
            "intent": result.get("intent", "other"),
            "risk_reasons": result.get("risk_reasons", []),
            "route_priority": result.get("route_priority", "P2_support"),
            "control_category": result.get("control_category", "normal_support"),
            "control_reasons": result.get("control_reasons", []),
            "control_confidence": result.get("control_confidence", 0.0),
            "risk_formulation": result.get("risk_formulation", {}),
            "response_contract": result.get("response_contract", {}),
            "memory_policy": result.get("memory_policy", "write_safe_summary"),
            "memory_policy_reason": result.get("memory_policy_reason", result.get("memory_policy", "")),
            "rag_used": bool(result.get("rag_used", False)),
            "rag_skipped_reason": str(result.get("rag_skipped_reason", "")),
            "example_ids": [
                str(example.get("chunk_id") or "")
                for example in retrieved_examples
                if isinstance(example, dict) and str(example.get("chunk_id") or "")
            ],
            "example_source_keys": [
                str(example.get("source_key") or "")
                for example in retrieved_examples
                if isinstance(example, dict) and str(example.get("source_key") or "")
            ],
            "validator_blocked": bool(result.get("validator_blocked", False)),
            "validator_reasons": result.get("validator_reasons", []),
            "suggested_actions": [] if delivery_status == "failed_no_reply" else result.get("suggested_actions", []),
            "session_summary": "" if delivery_status == "failed_no_reply" else result.get("session_summary", ""),
            "memory_candidates": [] if delivery_status == "failed_no_reply" else result.get("memory_candidates", []),
            "should_write_memory": False if delivery_status == "failed_no_reply" else result.get("should_write_memory", False),
            "memory_write_decisions": result.get("memory_write_decisions", []),
            "referenced_memories": referenced_memories,
            "referenced_counseling_examples": referenced_examples,
            "delivery_status": delivery_status,
            "failure_reason": result.get("failure_reason"),
            "retryable": bool(result.get("retryable", delivery_status == "failed_no_reply")),
        }
