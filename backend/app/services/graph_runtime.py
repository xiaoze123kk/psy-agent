from app.graphs.main_graph import build_main_graph
from app.services.counseling_vector_service import retrieve_counseling_examples


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
                "content": content,
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
        content = str(getattr(example, "content", "") or "").strip()
        if not content:
            continue
        references.append(
            {
                "source_key": str(getattr(example, "source_key", "") or ""),
                "source_name": str(getattr(example, "source_name", "") or ""),
                "mode": str(getattr(example, "mode", "") or ""),
                "score": float(getattr(example, "score", 0.0) or 0.0),
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
        response_mode = _response_mode_for_intent(str(result.get("intent", "other")))
        retrieved_examples = await retrieve_counseling_examples(
            {
                **input_state,
                "normalized_text": content.strip(),
                "risk_level": risk_level,
            },
            mode=response_mode,
            limit=3,
        )
        return {
            "assistant_text": result.get("assistant_text", ""),
            "risk_level": risk_level,
            "intent": result.get("intent", "other"),
            "risk_reasons": result.get("risk_reasons", []),
            "suggested_actions": result.get("suggested_actions", []),
            "session_summary": result.get("session_summary", ""),
            "memory_candidates": result.get("memory_candidates", []),
            "should_write_memory": result.get("should_write_memory", False),
            "referenced_memories": _memory_references(retrieved_memories, str(risk_level)),
            "referenced_counseling_examples": _counseling_references(retrieved_examples, str(risk_level)),
        }
