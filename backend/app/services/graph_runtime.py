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


def _safe_graph_update(node: str, state: dict, node_update: object) -> dict[str, object]:
    event: dict[str, object] = {
        "node": node,
        "status": "completed",
    }
    safe_keys = (
        "risk_level",
        "intent",
        "route_priority",
        "control_category",
        "rag_used",
        "rag_skipped_reason",
        "validator_blocked",
        "delivery_status",
    )
    for key in safe_keys:
        value = state.get(key)
        if value is None:
            continue
        if value == "" or value == [] or value == {}:
            continue
        event[key] = value

    if node == "response_validator" and isinstance(node_update, dict):
        event["validator_blocked"] = bool(node_update.get("validator_blocked", False))
        if node_update.get("delivery_status"):
            event["delivery_status"] = str(node_update["delivery_status"])
    return event


def _iter_node_updates(update: object):
    if isinstance(update, tuple) and len(update) == 2:
        update = update[1]
    if not isinstance(update, dict):
        return
    for node, node_update in update.items():
        if isinstance(node, str):
            yield node, node_update


class GraphRuntime:
    _compiled_graph = None

    def __init__(self) -> None:
        if GraphRuntime._compiled_graph is None:
            GraphRuntime._compiled_graph = build_main_graph()
        self.graph = GraphRuntime._compiled_graph

    def _build_input_state(
        self,
        *,
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
        return {
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

    def _graph_config(self, *, thread_id: str, user_id: str) -> dict[str, object]:
        return {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
            }
        }

    def _map_result(self, result: dict[str, object], *, retrieved_memories: list[dict] | None) -> dict[str, object]:
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
        input_state = self._build_input_state(
            thread_id=thread_id,
            user_id=user_id,
            content=content,
            input_type=input_type,
            user_mode=user_mode,
            recent_messages=recent_messages,
            last_summary=last_summary,
            memory_mode=memory_mode,
            companion_style=companion_style,
            nickname=nickname,
            retrieved_memories=retrieved_memories,
            memory_index=memory_index,
        )
        result = await self.graph.ainvoke(
            input_state,
            config=self._graph_config(thread_id=thread_id, user_id=user_id),
        )
        return self._map_result(result, retrieved_memories=retrieved_memories)

    async def stream_turn(
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
    ):
        input_state = self._build_input_state(
            thread_id=thread_id,
            user_id=user_id,
            content=content,
            input_type=input_type,
            user_mode=user_mode,
            recent_messages=recent_messages,
            last_summary=last_summary,
            memory_mode=memory_mode,
            companion_style=companion_style,
            nickname=nickname,
            retrieved_memories=retrieved_memories,
            memory_index=memory_index,
        )
        config = self._graph_config(thread_id=thread_id, user_id=user_id)
        state = dict(input_state)

        if not hasattr(self.graph, "astream"):
            result = await self.graph.ainvoke(input_state, config=config)
            yield "graph_result", self._map_result(result, retrieved_memories=retrieved_memories)
            return

        async for update in self.graph.astream(input_state, config=config, stream_mode="updates"):
            for node, node_update in _iter_node_updates(update):
                if isinstance(node_update, dict):
                    state.update(node_update)
                yield "graph_update", _safe_graph_update(node, state, node_update)

        yield "graph_result", self._map_result(state, retrieved_memories=retrieved_memories)
