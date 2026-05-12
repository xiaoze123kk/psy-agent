from app.graphs.main_graph import build_main_graph
from app.services.graph_trace_service import GraphTraceCollector


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
        "risk_source",
        "requires_safety_check",
        "intent",
        "route_priority",
        "control_category",
        "memory_policy",
        "memory_policy_reason",
        "rag_used",
        "rag_skipped_reason",
        "validator_blocked",
        "validator_reasons",
        "delivery_status",
        "failure_reason",
        "retryable",
        "should_write_memory",
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
    if isinstance(node_update, dict):
        if "retrieved_memories" in node_update and isinstance(node_update["retrieved_memories"], list):
            event["retrieved_memory_count"] = len(node_update["retrieved_memories"])
        if "retrieved_counseling_examples" in node_update and isinstance(node_update["retrieved_counseling_examples"], list):
            event["retrieved_example_count"] = len(node_update["retrieved_counseling_examples"])
        if "memory_candidates" in node_update and isinstance(node_update["memory_candidates"], list):
            event["memory_candidate_count"] = len(node_update["memory_candidates"])
        if "memory_write_decisions" in node_update and isinstance(node_update["memory_write_decisions"], list):
            event["memory_write_decision_count"] = len(node_update["memory_write_decisions"])
    return event


def _iter_node_updates(update: object):
    if isinstance(update, tuple) and len(update) == 2:
        update = update[1]
    if not isinstance(update, dict):
        return
    for node, node_update in update.items():
        if isinstance(node, str):
            yield node, node_update


def _split_stream_update(update: object) -> tuple[str | None, object]:
    if isinstance(update, tuple) and len(update) == 2 and isinstance(update[0], str):
        return update[0], update[1]
    return None, update


def _assistant_token_payload(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "assistant_token":
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        return None
    return {"text": text}


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
        session_digest: dict | None = None,
        memory_mode: str = "summary_only",
        companion_style: str = "",
        nickname: str | None = None,
        crisis_resource_region: str = "CN",
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
            "session_digest": session_digest or {},
            "memory_mode": memory_mode,
            "crisis_resource_region": crisis_resource_region or "CN",
            "tooling_enabled": True,
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

    def _map_result(
        self,
        result: dict[str, object],
        *,
        retrieved_memories: list[dict] | None,
        graph_trace: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
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
        mapped = {
            "assistant_text": assistant_text,
            "risk_level": risk_level,
            "intent": result.get("intent", "other"),
            "risk_reasons": result.get("risk_reasons", []),
            "semantic_risk": result.get("semantic_risk", {}),
            "risk_source": result.get("risk_source", ""),
            "risk_reason_codes": result.get("risk_reason_codes", []),
            "requires_safety_check": bool(result.get("requires_safety_check", False)),
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
            "session_digest": {} if delivery_status == "failed_no_reply" else result.get("session_digest", {}),
            "memory_candidates": [] if delivery_status == "failed_no_reply" else result.get("memory_candidates", []),
            "should_write_memory": False if delivery_status == "failed_no_reply" else result.get("should_write_memory", False),
            "memory_write_decisions": result.get("memory_write_decisions", []),
            "referenced_memories": referenced_memories,
            "referenced_counseling_examples": referenced_examples,
            "delivery_status": delivery_status,
            "failure_reason": result.get("failure_reason"),
            "retryable": bool(result.get("retryable", delivery_status == "failed_no_reply")),
            "tool_events": result.get("tool_events", []),
            "tool_trace_summary": result.get("tool_trace_summary", {}),
        }
        if graph_trace is not None:
            mapped["graph_trace"] = graph_trace
        return mapped

    async def _invoke_graph_with_trace(
        self,
        input_state: dict[str, object],
        *,
        config: dict[str, object],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        collector = GraphTraceCollector()
        if not hasattr(self.graph, "astream"):
            result = await self.graph.ainvoke(input_state, config=config)
            collector.record_node("graph_result", result)
            return result, collector.records

        state = dict(input_state)
        async for update in self.graph.astream(input_state, config=config, stream_mode="updates"):
            for node, node_update in _iter_node_updates(update):
                if isinstance(node_update, dict):
                    state.update(node_update)
                collector.record_node(node, node_update)
        return state, collector.records

    async def invoke_turn(
        self,
        thread_id: str,
        user_id: str,
        content: str,
        input_type: str = "text",
        user_mode: str = "adult",
        recent_messages: list[dict] | None = None,
        last_summary: str | None = None,
        session_digest: dict | None = None,
        memory_mode: str = "summary_only",
        companion_style: str = "",
        nickname: str | None = None,
        crisis_resource_region: str = "CN",
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
            session_digest=session_digest,
            memory_mode=memory_mode,
            companion_style=companion_style,
            nickname=nickname,
            crisis_resource_region=crisis_resource_region,
            retrieved_memories=retrieved_memories,
            memory_index=memory_index,
        )
        result, graph_trace = await self._invoke_graph_with_trace(
            input_state,
            config=self._graph_config(thread_id=thread_id, user_id=user_id),
        )
        return self._map_result(result, retrieved_memories=retrieved_memories, graph_trace=graph_trace)

    async def stream_turn(
        self,
        thread_id: str,
        user_id: str,
        content: str,
        input_type: str = "text",
        user_mode: str = "adult",
        recent_messages: list[dict] | None = None,
        last_summary: str | None = None,
        session_digest: dict | None = None,
        memory_mode: str = "summary_only",
        companion_style: str = "",
        nickname: str | None = None,
        crisis_resource_region: str = "CN",
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
            session_digest=session_digest,
            memory_mode=memory_mode,
            companion_style=companion_style,
            nickname=nickname,
            crisis_resource_region=crisis_resource_region,
            retrieved_memories=retrieved_memories,
            memory_index=memory_index,
        )
        config = self._graph_config(thread_id=thread_id, user_id=user_id)
        state = dict(input_state)
        collector = GraphTraceCollector()

        if not hasattr(self.graph, "astream"):
            result = await self.graph.ainvoke(input_state, config=config)
            graph_trace = [collector.record_node("graph_result", result)]
            yield "graph_result", self._map_result(
                result,
                retrieved_memories=retrieved_memories,
                graph_trace=graph_trace,
            )
            return

        async for update in self.graph.astream(input_state, config=config, stream_mode=["updates", "custom"]):
            stream_mode, payload = _split_stream_update(update)
            if stream_mode == "custom":
                token_payload = _assistant_token_payload(payload)
                if token_payload is not None:
                    yield "token", token_payload
                continue
            if stream_mode is not None and stream_mode != "updates":
                continue

            for node, node_update in _iter_node_updates(payload):
                if isinstance(node_update, dict):
                    state.update(node_update)
                trace_record = collector.record_node(node, node_update)
                graph_update = _safe_graph_update(node, state, node_update)
                graph_update["duration_ms"] = trace_record["duration_ms"]
                yield "graph_update", graph_update

        yield "graph_result", self._map_result(
            state,
            retrieved_memories=retrieved_memories,
            graph_trace=collector.records,
        )
