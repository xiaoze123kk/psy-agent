from __future__ import annotations

import unittest

from app.services.tooling import ToolGate, build_dialogue_tool_plan, summarize_tool_events


def make_state(
    *,
    risk_level: str = "L0",
    memory_mode: str = "summary_only",
    user_mode: str = "adult",
    crisis_resource_region: str = "CN",
    memory_index: list[dict] | None = None,
    retrieved_memories: list[dict] | None = None,
) -> dict[str, object]:
    return {
        "risk_level": risk_level,
        "memory_mode": memory_mode,
        "tooling_enabled": True,
        "profile": {"user_mode": user_mode, "nickname": "tester"},
        "user_mode": user_mode,
        "crisis_resource_region": crisis_resource_region,
        "memory_index": memory_index or [],
        "retrieved_memories": retrieved_memories or [],
        "recent_messages": [],
        "last_summary": "",
        "control_category": "normal_support",
        "route_priority": "P2_support",
    }


class ToolGateTests(unittest.TestCase):
    def test_gate_directly_blocks_disallowed_tools(self) -> None:
        gate = ToolGate(risk_level="L2", memory_mode="long_term")

        self.assertFalse(gate.allows("search_memories"))
        self.assertFalse(gate.allows("save_memory_summary"))
        self.assertTrue(gate.allows("get_safety_resources"))
        self.assertFalse(gate.allows("ask_knowledge"))

    def test_low_risk_plan_exposes_memory_and_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertEqual(tool_names, ["search_memories", "save_memory_summary", "get_safety_resources"])
        self.assertEqual(plan.allowed_tool_names, tool_names)
        self.assertNotIn("ask_knowledge", tool_names)
        self.assertFalse(plan.blocked_tool_names)

    def test_high_risk_plan_limits_to_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_safety_resources"])
        self.assertEqual(plan.allowed_tool_names, ["get_safety_resources"])
        self.assertIn("search_memories", plan.blocked_tool_names)
        self.assertIn("save_memory_summary", plan.blocked_tool_names)

    def test_memory_mode_off_limits_to_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(memory_mode="off"))

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_safety_resources"])


class MemoryToolHandlerTests(unittest.TestCase):
    def test_search_memories_handler_filters_internal_entries(self) -> None:
        state = make_state(
            memory_index=[
                {
                    "memory_id": "mem-1",
                    "memory_type": "preference",
                    "title": "Need reassurance",
                    "description": "User prefers reassurance before planning.",
                    "importance": 4,
                    "visibility": "user_visible",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
                {
                    "memory_id": "mem-2",
                    "memory_type": "safety_summary",
                    "title": "Internal note",
                    "description": "Sensitive internal note that should stay hidden.",
                    "importance": 5,
                    "visibility": "internal_safety",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
            ]
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["search_memories"]({"query": "reassurance", "limit": 2})

        self.assertEqual(result["query"], "reassurance")
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["memory_id"], "mem-1")
        self.assertEqual(item["memory_type"], "preference")
        self.assertNotIn("content", item)
        self.assertNotIn("mem-2", str(result))

    def test_save_memory_summary_handler_normalizes_candidates(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["save_memory_summary"](
            {
                "session_summary": "  This was a useful session.  ",
                "memory_candidates": [
                    {
                        "memory_type": "preference",
                        "title": "   Reassurance first   ",
                        "summary": "   User wants reassurance first.   ",
                        "content": "   User wants reassurance first.   ",
                        "importance": 9,
                        "tags": ["support", "support", "calm"],
                    },
                    {
                        "memory_type": "unknown_type",
                        "content": "   fallback summary candidate   ",
                        "importance": 0,
                    },
                ],
            }
        )

        self.assertEqual(result["session_summary"], "This was a useful session.")
        self.assertTrue(result["should_write_memory"])
        self.assertEqual(result["memory_policy"], "write_safe_summary")
        self.assertEqual(len(result["memory_candidates"]), 2)
        self.assertEqual(result["memory_candidates"][0]["importance"], 5)
        self.assertEqual(result["memory_candidates"][0]["title"], "Reassurance first")
        self.assertEqual(result["memory_candidates"][1]["memory_type"], "session_summary")

    def test_get_safety_resources_handler_uses_region_and_audience(self) -> None:
        state = make_state(user_mode="teen", crisis_resource_region="US")
        plan = build_dialogue_tool_plan(state)

        teen_resources = plan.tool_handlers["get_safety_resources"]({"region": "US", "audience": "teen"})
        adult_resources = plan.tool_handlers["get_safety_resources"]({"region": "US", "audience": "adult"})

        self.assertEqual(teen_resources["region"], "US")
        self.assertEqual(adult_resources["region"], "US")
        self.assertIn("school", {item["resource_type"] for item in teen_resources["items"]})
        self.assertIn("adult_support", {item["resource_type"] for item in adult_resources["items"]})


class ToolAuditSummaryTests(unittest.TestCase):
    def test_tool_event_summary_is_minimal(self) -> None:
        summary = summarize_tool_events(
            [
                {
                    "tool_call_id": "call-1",
                    "name": "search_memories",
                    "arguments": {"query": "need reassurance"},
                    "status": "completed",
                    "error": None,
                },
                {
                    "tool_call_id": "call-2",
                    "name": "save_memory_summary",
                    "arguments": {"session_summary": "secret"},
                    "status": "error",
                    "error": "handler_error",
                },
            ]
        )

        self.assertEqual(summary["tool_count"], 2)
        self.assertEqual(summary["tool_names"], ["search_memories", "save_memory_summary"])
        self.assertEqual(summary["status_counts"]["completed"], 1)
        self.assertEqual(summary["status_counts"]["error"], 1)
        self.assertEqual(summary["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
