from __future__ import annotations

import unittest

from app.services.graph_runtime import GraphRuntime


class FakeStreamingGraph:
    async def astream(self, input_state, config=None, stream_mode=None):
        yield {
            "risk_classifier": {
                "risk_level": "L0",
                "normalized_text": "private user text",
                "response_contract": {"secret": "do not leak"},
            }
        }
        yield {
            "example_retriever": {
                "rag_used": True,
                "rag_skipped_reason": "enabled",
                "retrieved_counseling_examples": [{"content": "private rag passage"}],
            }
        }
        yield {
            "response_validator": {
                "assistant_text": "I am here.",
                "suggested_actions": ["Say more"],
                "intent": "vent",
                "delivery_status": "generated",
                "validator_blocked": False,
            }
        }


class GraphRuntimeStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_turn_progress_events_do_not_leak_private_context(self) -> None:
        runtime = GraphRuntime.__new__(GraphRuntime)
        runtime.graph = FakeStreamingGraph()

        progress_events: list[dict[str, object]] = []
        final_result: dict[str, object] | None = None
        async for event_name, data in runtime.stream_turn(
            thread_id="thread-1",
            user_id="user-1",
            content="hello",
            recent_messages=[{"role": "user", "content": "private recent message"}],
            retrieved_memories=[{"content": "private memory", "visibility": "user_visible"}],
        ):
            if event_name == "graph_update":
                progress_events.append(data)
            elif event_name == "graph_result":
                final_result = data

        self.assertGreaterEqual(len(progress_events), 3)
        progress_payload = str(progress_events)
        trace_payload = str(final_result.get("graph_trace") if final_result else "")
        self.assertNotIn("private user text", progress_payload)
        self.assertNotIn("private recent message", progress_payload)
        self.assertNotIn("private memory", progress_payload)
        self.assertNotIn("private rag passage", progress_payload)
        self.assertNotIn("response_contract", progress_payload)
        self.assertNotIn("private user text", trace_payload)
        self.assertNotIn("private recent message", trace_payload)
        self.assertNotIn("private memory", trace_payload)
        self.assertNotIn("private rag passage", trace_payload)
        self.assertNotIn("response_contract", trace_payload)
        self.assertIn("risk_classifier", progress_payload)
        self.assertTrue(all("duration_ms" in event for event in progress_events))
        self.assertIsNotNone(final_result)
        self.assertEqual(final_result["assistant_text"], "I am here.")
        self.assertGreaterEqual(len(final_result["graph_trace"]), 3)
