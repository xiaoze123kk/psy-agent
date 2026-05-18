from __future__ import annotations

import unittest

from app.services.graph_runtime import GraphRuntime


def test_map_result_includes_risk_policy_metadata() -> None:
    runtime = object.__new__(GraphRuntime)
    result = runtime._map_result(
        {
            "assistant_text": "我在。",
            "risk_level": "L3",
            "risk_domain": "self_harm",
            "immediacy": "near_term",
            "risk_confidence": "high",
            "protective_signals": ["still_talking"],
            "risk_phase": "first_contact",
            "risk_response_policy": {"length_profile": "brief_first_contact"},
            "tool_gate_mode": "safety_context",
            "safety_context_pack": {"schema_version": 1},
            "experience_validator_reasons": [],
            "experience_validator_warnings": ["too_many_questions"],
            "experience_validator_blocking_reasons": [],
            "validator_severity": "warning",
            "delivery_status": "generated",
        },
        retrieved_memories=[],
    )

    assert result["risk_domain"] == "self_harm"
    assert result["immediacy"] == "near_term"
    assert result["risk_phase"] == "first_contact"
    assert result["tool_gate_mode"] == "safety_context"
    assert result["risk_response_policy"]["length_profile"] == "brief_first_contact"
    assert result["validator_severity"] == "warning"
    assert result["experience_validator_warnings"] == ["too_many_questions"]


def test_map_result_includes_compact_context_pack() -> None:
    runtime = object.__new__(GraphRuntime)
    pack = {
        "schema_version": 1,
        "state": {"summary_for_prompt": "用户还在同一条情绪线上。"},
        "event": {"type": "compact_event"},
    }

    result = runtime._map_result(
        {
            "assistant_text": "我在。",
            "risk_level": "L0",
            "compact_context_pack": pack,
            "delivery_status": "generated",
        },
        retrieved_memories=[],
    )

    assert result["compact_context_pack"] == pack


class FakeStreamingGraph:
    async def astream(self, input_state, config=None, stream_mode=None):
        yield {
            "risk_classifier": {
                "risk_level": "L0",
                "normalized_text": "private user text",
                "response_contract": {"secret": "do not leak"},
            }
        }
        yield ("custom", {"type": "assistant_token", "text": "I am "})
        yield {
            "example_retriever": {
                "rag_used": True,
                "rag_skipped_reason": None,
                "rag_trace_summary": {
                    "status": "hit",
                    "hit_count": 1,
                    "embedding_duration_ms": 12,
                    "milvus_duration_ms": 8,
                    "total_duration_ms": 20,
                },
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
                "validator_severity": "warning",
                "experience_validator_warnings": ["too_many_questions"],
            }
        }


class GraphRuntimeStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_turn_progress_events_do_not_leak_private_context(self) -> None:
        runtime = GraphRuntime.__new__(GraphRuntime)
        runtime.graph = FakeStreamingGraph()

        progress_events: list[dict[str, object]] = []
        token_events: list[str] = []
        event_order: list[str] = []
        final_result: dict[str, object] | None = None
        async for event_name, data in runtime.stream_turn(
            thread_id="thread-1",
            user_id="user-1",
            content="hello",
            recent_messages=[{"role": "user", "content": "private recent message"}],
            retrieved_memories=[{"content": "private memory", "visibility": "user_visible"}],
        ):
            event_order.append(event_name)
            if event_name == "graph_update":
                progress_events.append(data)
            elif event_name == "token":
                token_events.append(str(data["text"]))
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
        self.assertTrue(any(event.get("retrieved_example_count") == 1 for event in progress_events))
        self.assertTrue(any((event.get("rag_trace_summary") or {}).get("status") == "hit" for event in progress_events))
        self.assertTrue(any(event.get("validator_severity") == "warning" for event in progress_events))
        self.assertEqual(token_events, ["I am "])
        self.assertLess(event_order.index("token"), event_order.index("graph_result"))
        self.assertIsNotNone(final_result)
        self.assertEqual(final_result["assistant_text"], "I am here.")
        self.assertEqual(final_result["rag_skipped_reason"], "")
        self.assertEqual(final_result["rag_trace_summary"]["status"], "hit")
        self.assertEqual(final_result["validator_severity"], "warning")
        self.assertEqual(final_result["experience_validator_warnings"], ["too_many_questions"])
        self.assertGreaterEqual(len(final_result["graph_trace"]), 3)
