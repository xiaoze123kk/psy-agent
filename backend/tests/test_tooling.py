from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.tooling import ALL_RISK_LEVELS, LOW_RISK_LEVELS, TOOL_SPEC_BY_NAME, ToolGate, build_dialogue_tool_plan, summarize_tool_events


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

        self.assertEqual(tool_names, ["search_memories", "save_memory_summary", "get_safety_resources", "web_search", "get_current_time", "get_weather"])
        self.assertEqual(plan.allowed_tool_names, tool_names)
        self.assertNotIn("ask_knowledge", tool_names)
        self.assertFalse(plan.blocked_tool_names)

    def test_high_risk_plan_limits_to_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_safety_resources", "get_current_time"])
        self.assertEqual(plan.allowed_tool_names, ["get_safety_resources", "get_current_time"])
        self.assertIn("search_memories", plan.blocked_tool_names)
        self.assertIn("save_memory_summary", plan.blocked_tool_names)

    def test_memory_mode_off_limits_to_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(memory_mode="off"))

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_safety_resources", "get_current_time"])


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

    def test_save_memory_summary_handles_goal_candidate(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["save_memory_summary"](
            {
                "session_summary": "User set a small goal.",
                "memory_candidates": [
                    {
                        "memory_type": "goal",
                        "title": "每天散步",
                        "content": "每天下楼散步至少10分钟",
                        "importance": 4,
                        "tags": ["散步", "运动"],
                        "structured_value": {"goal_status": "active", "goal_category": "routine"},
                    },
                ],
            }
        )

        self.assertEqual(result["session_summary"], "User set a small goal.")
        self.assertEqual(len(result["memory_candidates"]), 1)
        candidate = result["memory_candidates"][0]
        self.assertEqual(candidate["memory_type"], "goal")
        self.assertEqual(candidate["content"], "每天下楼散步至少10分钟")
        self.assertEqual(candidate["structured_value"]["goal_status"], "active")
        self.assertEqual(candidate["structured_value"]["goal_category"], "routine")

    def test_save_memory_summary_goal_candidate_strips_invalid_structured_value(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["save_memory_summary"](
            {
                "session_summary": "Goal test.",
                "memory_candidates": [
                    {
                        "memory_type": "goal",
                        "content": "每天冥想5分钟",
                        "structured_value": "not-a-dict",
                    },
                ],
            }
        )

        candidate = result["memory_candidates"][0]
        self.assertNotIn("structured_value", candidate)

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


class WebSearchToolTests(unittest.TestCase):
    def test_web_search_spec_is_registered(self) -> None:
        spec = TOOL_SPEC_BY_NAME.get("web_search")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "web_search")
        self.assertEqual(spec.enabled_by_default, True)
        self.assertEqual(spec.allowed_risk_levels, LOW_RISK_LEVELS)
        tool_def = spec.to_deepseek_tool()
        self.assertEqual(tool_def["function"]["name"], "web_search")
        self.assertIn("query", tool_def["function"]["parameters"]["properties"])

    def test_web_search_appears_in_low_risk_plan(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertIn("web_search", tool_names)
        self.assertIn("web_search", plan.allowed_tool_names)
        self.assertNotIn("web_search", plan.blocked_tool_names)

    def test_web_search_blocked_at_high_risk(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertNotIn("web_search", tool_names)
        self.assertIn("web_search", plan.blocked_tool_names)

    @staticmethod
    def _search_result(title: str, url: str, snippet: str) -> dict[str, object]:
        return {"title": title, "href": url, "body": snippet}

    def test_web_search_handler_returns_search_results(self) -> None:
        from app.services.search_service import SearchResult

        mock_results = [
            SearchResult(
                title="北京心理援助热线",
                url="https://example.com/beijing",
                snippet="北京市心理援助热线：010-82951332",
            ),
        ]

        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch(
            "app.services.search_service.search_web",
            return_value=(mock_results, None),
        ):
            result = plan.tool_handlers["web_search"]({"query": "北京心理援助热线"})

        self.assertEqual(result["query"], "北京心理援助热线")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["title"], "北京心理援助热线")
        self.assertEqual(item["url"], "https://example.com/beijing")
        self.assertIn("010-82951332", item["snippet"])

    def test_web_search_handler_empty_query(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.search_service.search_web", return_value=([], None)):
            result = plan.tool_handlers["web_search"]({"query": "", "max_results": 3})

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])

    def test_web_search_handler_records_preview(self) -> None:
        from app.services.search_service import SearchResult

        mock_results = [
            SearchResult(
                title="Hotline",
                url="https://example.com/hotline",
                snippet="A helpful resource.",
            ),
        ]

        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.search_service.search_web", return_value=(mock_results, None)):
            plan.tool_handlers["web_search"]({"query": "help"})

        previews = plan.audit_capture.previews
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["name"], "web_search")
        self.assertEqual(previews[0]["status"], "completed")

    def test_web_search_handler_reports_error_status(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.search_service.search_web", return_value=([], "timeout")):
            result = plan.tool_handlers["web_search"]({"query": "help"})

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["error"], "timeout")
        previews = plan.audit_capture.previews
        self.assertEqual(previews[0]["status"], "error")
        self.assertEqual(previews[0]["error"], "search_failed: timeout")


class GetCurrentTimeToolTests(unittest.TestCase):
    def test_get_current_time_spec_is_registered(self) -> None:
        spec = TOOL_SPEC_BY_NAME.get("get_current_time")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "get_current_time")
        self.assertEqual(spec.enabled_by_default, True)
        self.assertEqual(spec.allowed_risk_levels, ALL_RISK_LEVELS)
        tool_def = spec.to_deepseek_tool()
        self.assertEqual(tool_def["function"]["name"], "get_current_time")
        self.assertEqual(tool_def["function"]["parameters"]["properties"], {})

    def test_get_current_time_appears_in_low_risk_plan(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertIn("get_current_time", tool_names)

    def test_get_current_time_available_at_high_risk(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertIn("get_current_time", tool_names)

    def test_get_current_time_available_with_memory_off(self) -> None:
        plan = build_dialogue_tool_plan(make_state(memory_mode="off"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertIn("get_current_time", tool_names)

    def test_get_current_time_handler_returns_time_fields(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["get_current_time"]({})

        self.assertIn("utc_iso", result)
        self.assertIn("local_iso", result)
        self.assertIn("timezone", result)
        self.assertIn("weekday", result)
        self.assertIn("session_elapsed_seconds", result)
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertIn(result["weekday"], {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"})

    def test_get_current_time_session_elapsed_starts_at_zero(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["get_current_time"]({})
        self.assertEqual(result["session_elapsed_seconds"], 0.0)

    def test_get_current_time_session_elapsed_increases(self) -> None:
        import time

        state = make_state()
        plan = build_dialogue_tool_plan(state)

        first = plan.tool_handlers["get_current_time"]({})
        time.sleep(0.05)
        second = plan.tool_handlers["get_current_time"]({})

        self.assertGreater(second["session_elapsed_seconds"], first["session_elapsed_seconds"])

    def test_get_current_time_records_preview(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        plan.tool_handlers["get_current_time"]({})

        previews = plan.audit_capture.previews
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["name"], "get_current_time")
        self.assertEqual(previews[0]["status"], "completed")


class GetWeatherToolTests(unittest.TestCase):
    def test_get_weather_spec_is_registered(self) -> None:
        spec = TOOL_SPEC_BY_NAME.get("get_weather")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "get_weather")
        self.assertEqual(spec.enabled_by_default, True)
        self.assertEqual(spec.allowed_risk_levels, LOW_RISK_LEVELS)
        tool_def = spec.to_deepseek_tool()
        self.assertEqual(tool_def["function"]["name"], "get_weather")
        self.assertIn("city", tool_def["function"]["parameters"]["properties"])

    def test_get_weather_appears_in_low_risk_plan(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertIn("get_weather", tool_names)

    def test_get_weather_blocked_at_high_risk(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertNotIn("get_weather", tool_names)

    def test_get_weather_handler_returns_weather(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch(
            "app.services.weather_service.get_weather",
            return_value=("晴 15°C 湿度45% 风速3km/h", None),
        ):
            result = plan.tool_handlers["get_weather"]({"city": "Beijing"})

        self.assertEqual(result["city"], "Beijing")
        self.assertIn("晴", result["weather"])
        self.assertNotIn("error", result)

    def test_get_weather_handler_reports_error(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.weather_service.get_weather", return_value=("", "timeout")):
            result = plan.tool_handlers["get_weather"]({"city": "Shanghai"})

        self.assertEqual(result["weather"], "")
        self.assertEqual(result["error"], "timeout")
        previews = plan.audit_capture.previews
        self.assertEqual(previews[0]["status"], "error")

    def test_get_weather_defaults_city(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch(
            "app.services.weather_service.get_weather",
            return_value=("阴 10°C 湿度60% 风速2km/h", None),
        ):
            result = plan.tool_handlers["get_weather"]({})

        self.assertEqual(result["city"], "Beijing")


if __name__ == "__main__":
    unittest.main()
