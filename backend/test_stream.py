import asyncio
from app.services.graph_runtime import GraphRuntime

async def test():
    runtime = GraphRuntime()
    print("Starting stream test...")
    events = runtime.stream_turn(
        thread_id="test-cli",
        user_id="test-cli",
        content="我今天心情不太好",
        input_type="text",
        user_mode="adult",
        recent_messages=[],
        last_summary="",
        session_digest={},
        user_profile_digest={},
        goal_state={},
        user_context_pack={},
        memory_mode="summary_only",
        retrieved_memories=[],
        memory_index=[],
    )
    nodes_seen = []
    tokens = []
    try:
        async for event_name, data in events:
            if event_name == "token":
                tokens.append(data.get("text", ""))
                print(data.get("text", ""), end="", flush=True)
            elif event_name == "graph_update":
                node = data.get("node", "?")
                dur = data.get("duration_ms", 0)
                nodes_seen.append(f"{node}({dur}ms)")
                print(f"\n  NODE: {node} ({dur}ms)")
            elif event_name == "graph_result":
                rag = data.get("rag_used", False)
                text_len = len(data.get("assistant_text", ""))
                print(f"\n  RESULT: rag_used={rag}, text_len={text_len}")
    except Exception as e:
        import traceback
        traceback.print_exc()

    print(f"\nNodes: {' -> '.join(nodes_seen)}")
    print(f"Tokens: {len(tokens)}, total chars: {sum(len(t) for t in tokens)}")

asyncio.run(test())
