from app.graphs.main_graph import build_main_graph


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
    ) -> dict[str, object]:
        input_state = {
            "thread_id": thread_id,
            "user_id": user_id,
            "user_text": content,
            "input_type": input_type,
            "user_mode": user_mode,
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

        return {
            "assistant_text": result.get("assistant_text", ""),
            "risk_level": result.get("risk_level", "L0"),
            "intent": result.get("intent", "other"),
            "suggested_actions": result.get("suggested_actions", []),
            "session_summary": result.get("session_summary", ""),
            "should_write_memory": result.get("should_write_memory", False),
        }
