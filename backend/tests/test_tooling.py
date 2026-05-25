from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.deepseek_client import ToolChatResult
from app.services.search_service import SearchResult
from app.services.tooling import (
    ALL_RISK_LEVELS,
    LOW_RISK_LEVELS,
    TOOL_SPEC_BY_NAME,
    ToolGate,
    build_dialogue_tool_plan,
    _fallback_answer_from_prefetched_web,
    _prefetch_search_query,
    run_dialogue_reply_with_tools,
    summarize_tool_events,
)


def make_state(
    *,
    risk_level: str = "L0",
    memory_mode: str = "summary_only",
    user_mode: str = "adult",
    crisis_resource_region: str = "CN",
    memory_index: list[dict] | None = None,
    retrieved_memories: list[dict] | None = None,
    recent_messages: list[dict] | None = None,
    last_summary: str = "",
    session_summary: str = "",
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
        "recent_messages": recent_messages or [],
        "last_summary": last_summary,
        "session_summary": session_summary,
        "control_category": "normal_support",
        "route_priority": "P2_support",
    }


class ToolGateTests(unittest.TestCase):
    def test_gate_directly_blocks_disallowed_tools(self) -> None:
        gate = ToolGate(risk_level="L2", memory_mode="long_term")

        self.assertTrue(gate.allows("search_memories"))
        self.assertFalse(gate.allows("save_memory_summary"))
        self.assertTrue(gate.allows("get_safety_resources"))
        self.assertFalse(gate.allows("ask_knowledge"))

    def test_low_risk_plan_exposes_memory_and_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertEqual(tool_names, ["search_memories", "save_memory_summary", "get_safety_resources", "web_search", "get_current_time", "get_weather", "summarize_session"])
        self.assertEqual(plan.allowed_tool_names, tool_names)
        self.assertNotIn("ask_knowledge", tool_names)
        self.assertEqual(plan.blocked_tool_names, ["safe_web_search"])

    def test_high_risk_plan_exposes_safety_context_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        self.assertEqual(
            [tool["function"]["name"] for tool in plan.tools],
            ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"],
        )
        self.assertEqual(
            plan.allowed_tool_names,
            ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"],
        )
        self.assertIn("save_memory_summary", plan.blocked_tool_names)
        self.assertIn("web_search", plan.blocked_tool_names)
        self.assertIn("get_weather", plan.blocked_tool_names)

    def test_blocked_context_keeps_only_minimal_tools(self) -> None:
        state = make_state(risk_level="L1")
        state["tool_gate_mode"] = "blocked_context"

        plan = build_dialogue_tool_plan(state)

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_current_time", "summarize_session"])

    def test_memory_mode_off_limits_to_safety_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(memory_mode="off"))

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_safety_resources", "get_current_time", "summarize_session"])


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

    def test_high_risk_search_memories_returns_safe_context_only(self) -> None:
        state = make_state(
            risk_level="L3",
            memory_index=[
                {
                    "memory_id": "pref-1",
                    "memory_type": "preference",
                    "title": "Style",
                    "description": "User dislikes command-like replies.",
                    "importance": 4,
                    "visibility": "user_visible",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
                {
                    "memory_id": "state-1",
                    "memory_type": "state",
                    "title": "Ordinary state",
                    "description": "Should not show in safety context.",
                    "importance": 4,
                    "visibility": "user_visible",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
            ],
        )
        state["tool_gate_mode"] = "safety_context"
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["search_memories"]({"query": "style", "limit": 5})

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["memory_id"], "pref-1")
        self.assertNotIn("state-1", str(result))


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

    def test_tool_plan_and_handler_record_diagnostics_with_module_logger(self) -> None:
        with patch(
            "app.services.search_service.search_web",
            return_value=([], None),
        ), self.assertLogs("app.services.tooling", level="DEBUG") as logs:
            plan = build_dialogue_tool_plan(make_state())
            plan.tool_handlers["web_search"]({"query": "help"})

        log_text = "\n".join(logs.output)
        self.assertIn("Dialogue tool plan built", log_text)
        self.assertIn("web_search tool completed", log_text)
        self.assertIn("status=completed", log_text)
        self.assertNotIn("debug_tooling.log", log_text)

    def test_prefetch_visit_china_query_uses_current_year_dynamically(self) -> None:
        with patch("app.services.tooling.datetime") as fake_datetime:
            fake_datetime.now.return_value.year = 2027

            query = _prefetch_search_query("特朗普访华是什么时候？")

        self.assertIn("特朗普", query)
        self.assertIn("访华", query)
        self.assertIn("2027", query)
        self.assertIn("国事访问", query)
        self.assertIn("外交部", query)
        self.assertNotIn("是什么时候", query)
        self.assertNotIn("2026", query)

    def test_prefetch_death_time_query_adds_current_year_and_obituary_terms(self) -> None:
        with patch("app.services.tooling.datetime") as fake_datetime:
            fake_datetime.now.return_value.year = 2027

            query = _prefetch_search_query("张雪峰去世时间是什么？")

        self.assertIn("张雪峰去世时间是什么？", query)
        self.assertIn("最新", query)
        self.assertIn("2027", query)
        self.assertIn("讣告", query)
        self.assertNotIn("2026", query)

    def test_prefetched_fallback_answer_omits_raw_url_and_normalizes_date_spacing(self) -> None:
        answer = _fallback_answer_from_prefetched_web(
            "特朗普 访华 2026 国事访问 外交部",
            {
                "count": 1,
                "items": [
                    {
                        "title": "特朗普 访华 2026 国事访问 外交部 - 搜索摘要",
                        "url": "https://www.sogou.com/web?query=trump+2026",
                        "snippet": "特朗普 于 2026 年5月13日至15日对中国进行 国事访问 ，",
                    }
                ],
            },
        )

        self.assertIn("2026年5月13日至15日", answer)
        self.assertNotIn("2026 年", answer)
        self.assertNotIn("https://", answer)


class WebSearchPrefetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_fact_question_prefetches_web_search_before_model_reply(self) -> None:
        state = make_state()
        state["normalized_text"] = "张雪峰去世时间是什么？"
        plan = build_dialogue_tool_plan(state)
        fake_tool_result = ToolChatResult(
            content="查到的公开信息显示，张雪峰于2026年3月24日15时50分在苏州逝世。",
            tool_events=[],
            finish_reason="stop",
            messages=[],
        )
        search_result = SearchResult(
            title="张雪峰去世",
            url="https://example.com/zhang",
            snippet="张雪峰于2026年3月24日15时50分在苏州逝世。",
        )

        with patch(
            "app.services.search_service.search_web",
            return_value=([search_result], None),
        ) as search_web, patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(return_value=fake_tool_result),
        ) as chat_with_tools:
            result = await run_dialogue_reply_with_tools(
                state,
                system_prompt="system",
                user_prompt="user",
                tool_plan=plan,
            )

        search_web.assert_called_once()
        self.assertEqual(result["assistant_text"], fake_tool_result.content)
        self.assertEqual(result["tool_events"][0]["name"], "web_search")
        self.assertEqual(result["tool_events"][0]["status"], "completed")
        sent_messages = chat_with_tools.call_args.args[0]
        self.assertIn("Pre-fetched web_search result", sent_messages[0]["content"])
        self.assertIn("2026年3月24日15时50分", sent_messages[0]["content"])

    async def test_prefetched_web_search_supplies_fallback_when_model_is_empty(self) -> None:
        state = make_state()
        state["normalized_text"] = "张雪峰去世时间是什么？"
        plan = build_dialogue_tool_plan(state)
        empty_tool_result = ToolChatResult(
            content=None,
            tool_events=[],
            finish_reason="request_failed",
            messages=[],
        )
        search_result = SearchResult(
            title="张雪峰去世",
            url="https://example.com/zhang",
            snippet="张雪峰于2026年3月24日15时50分因心源性猝死，经抢救无效在苏州逝世。",
        )

        with patch(
            "app.services.search_service.search_web",
            return_value=([search_result], None),
        ), patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(return_value=empty_tool_result),
        ):
            result = await run_dialogue_reply_with_tools(
                state,
                system_prompt="system",
                user_prompt="user",
                tool_plan=plan,
            )

        self.assertIn("2026年3月24日15时50分", result["assistant_text"])
        self.assertEqual(result["tool_trace_summary"]["status_counts"]["completed"], 1)

    async def test_prefetched_fact_overrides_model_when_model_contradicts_search(self) -> None:
        state = make_state()
        state["normalized_text"] = "张雪峰去世时间是什么？"
        plan = build_dialogue_tool_plan(state)
        wrong_tool_result = ToolChatResult(
            content="张雪峰老师还健在，没有去世的消息。",
            tool_events=[],
            finish_reason="stop",
            messages=[],
        )
        search_result = SearchResult(
            title="张雪峰去世时间是什么？ 最新 2026 讣告 - 搜索摘要",
            url="https://www.sogou.com/web?query=zhangxuefeng+2026",
            snippet=(
                "推荐您搜索 年仅 最新 资讯 根据张雪峰官方账号在3月24日晚间发布的讣告，"
                "张雪峰因突发心源性猝死，经全力抢救无效，于2026年3月24日15时50分在苏州逝世。"
            ),
        )

        with patch(
            "app.services.search_service.search_web",
            return_value=([search_result], None),
        ), patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(return_value=wrong_tool_result),
        ):
            result = await run_dialogue_reply_with_tools(
                state,
                system_prompt="system",
                user_prompt="user",
                tool_plan=plan,
            )

        self.assertIn("2026年3月24日15时50分", result["assistant_text"])
        self.assertNotIn("健在", result["assistant_text"])

    async def test_prefetched_fact_overrides_stale_model_date(self) -> None:
        state = make_state()
        state["normalized_text"] = "特朗普访华是什么时候？"
        plan = build_dialogue_tool_plan(state)
        stale_tool_result = ToolChatResult(
            content="特朗普上一次访华是在2017年11月8日至10日。",
            tool_events=[],
            finish_reason="stop",
            messages=[],
        )
        search_result = SearchResult(
            title="特朗普访华是什么时候？ 最新 2026 - 搜索摘要",
            url="https://www.sogou.com/web?query=trump+2026",
            snippet="美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。",
        )

        with patch(
            "app.services.search_service.search_web",
            return_value=([search_result], None),
        ), patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(return_value=stale_tool_result),
        ):
            result = await run_dialogue_reply_with_tools(
                state,
                system_prompt="system",
                user_prompt="user",
                tool_plan=plan,
            )

        self.assertIn("2026年5月13日至15日", result["assistant_text"])
        self.assertNotIn("2017年", result["assistant_text"])

    async def test_visit_china_question_searches_latest_current_year_context(self) -> None:
        state = make_state()
        state["normalized_text"] = "特朗普访华是什么时候？"
        plan = build_dialogue_tool_plan(state)
        fake_tool_result = ToolChatResult(
            content="特朗普最近一次访华是2026年5月13日至15日。",
            tool_events=[],
            finish_reason="stop",
            messages=[],
        )

        with patch(
            "app.services.search_service.search_web",
            return_value=(
                [
                    SearchResult(
                        title="特朗普访华",
                        url="https://example.com/trump",
                        snippet="特朗普于2026年5月13日至15日对中国进行国事访问。",
                    )
                ],
                None,
            ),
        ) as search_web, patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(return_value=fake_tool_result),
        ):
            await run_dialogue_reply_with_tools(
                state,
                system_prompt="system",
                user_prompt="user",
                tool_plan=plan,
            )

        query = search_web.call_args.args[0]
        self.assertIn("2026", query)
        self.assertIn("国事访问", query)


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
        self.assertEqual(result["timezone"], "Asia/Wuhan")
        self.assertIn("day_period", result)
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


class SummarizeSessionToolTests(unittest.TestCase):
    def test_summarize_session_spec_is_registered(self) -> None:
        from app.services.tooling import TOOL_SPEC_BY_NAME

        spec = TOOL_SPEC_BY_NAME.get("summarize_session")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "summarize_session")
        self.assertEqual(spec.enabled_by_default, True)
        from app.services.tooling import ALL_RISK_LEVELS

        self.assertEqual(spec.allowed_risk_levels, ALL_RISK_LEVELS)
        tool_def = spec.to_deepseek_tool()
        self.assertEqual(tool_def["function"]["name"], "summarize_session")
        self.assertIn("format", tool_def["function"]["parameters"]["properties"])
        self.assertIn("brief", tool_def["function"]["parameters"]["properties"]["format"]["enum"])
        self.assertIn("detailed", tool_def["function"]["parameters"]["properties"]["format"]["enum"])
        self.assertIn("themes_only", tool_def["function"]["parameters"]["properties"]["format"]["enum"])
        self.assertIn("progress", tool_def["function"]["parameters"]["properties"]["format"]["enum"])

    def test_summarize_session_appears_in_low_risk_plan(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertIn("summarize_session", tool_names)
        self.assertIn("summarize_session", plan.allowed_tool_names)
        self.assertNotIn("summarize_session", plan.blocked_tool_names)

    def test_summarize_session_available_at_high_risk(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertIn("summarize_session", tool_names)

    def test_summarize_session_available_with_memory_off(self) -> None:
        plan = build_dialogue_tool_plan(make_state(memory_mode="off"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertIn("summarize_session", tool_names)

    def test_summarize_session_brief_format_returns_overview(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "我最近工作压力很大", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "听起来你正在经历一段困难时期，愿意多说一些吗？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
                {"id": "m3", "role": "user", "content": "领导总是给我加活，我感觉喘不过气", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:01:00"},
                {"id": "m4", "role": "assistant", "content": "这种感觉很正常，被过度要求会让人窒息。你觉得最让你难受的是什么？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:01:10"},
            ],
            last_summary="用户表达了职场压力",
            session_summary="用户讨论了职场压力和与领导的沟通困难",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "brief"})

        self.assertEqual(result["format"], "brief")
        self.assertIn("turn_count", result)
        self.assertGreater(result["turn_count"], 0)
        self.assertIn("current_turn_topic", result)
        self.assertIn("source", result)
        self.assertEqual(result["source"], "conversation_state")

    def test_summarize_session_detailed_format_includes_themes_and_mood(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "我今天感觉非常焦虑，睡不好", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "焦虑和失眠确实会相互影响。你愿意描述一下是什么让你感到焦虑吗？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
                {"id": "m3", "role": "user", "content": "主要是工作上的事情", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:01:00"},
                {"id": "m4", "role": "assistant", "content": "我建议你可以试试每天睡前写下当天最困扰你的三件事，把焦虑从脑子里搬出来。", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:01:10"},
            ],
            last_summary="用户表达了焦虑和失眠",
            session_summary="用户讨论焦虑和失眠问题，与工作压力相关",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "detailed"})

        self.assertEqual(result["format"], "detailed")
        self.assertIn("overview", result)
        self.assertIn("topics", result)
        self.assertIsInstance(result["topics"], list)
        self.assertGreater(len(result["topics"]), 0)
        self.assertIn("mood_indicators", result)
        self.assertIsInstance(result["mood_indicators"], list)
        self.assertIn("suggestions_given", result)
        self.assertIsInstance(result["suggestions_given"], list)

    def test_summarize_session_themes_only_returns_only_themes(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "我和家人的关系最近很紧张", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "家人关系是很多人都会面临的挑战，你愿意具体说说吗？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
            ],
            last_summary="用户表达了家庭关系紧张",
            session_summary="用户讨论家庭关系困难",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "themes_only"})

        self.assertEqual(result["format"], "themes_only")
        self.assertIn("themes", result)
        self.assertIsInstance(result["themes"], list)
        self.assertGreater(len(result["themes"]), 0)
        self.assertNotIn("overview", result)
        self.assertNotIn("suggestions_given", result)
        self.assertNotIn("mood_indicators", result)

    def test_summarize_session_progress_format_includes_topic_changes(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "上周我开始了散步，感觉有点效果", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "很高兴听到散步对你有帮助！具体感觉哪些方面改善了？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
                {"id": "m3", "role": "user", "content": "睡眠好像好了一点，但还是会半夜醒来", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:01:00"},
            ],
            last_summary="用户分享了散步的积极效果和睡眠改善",
            session_summary="用户讨论了散步对焦虑的缓解效果和睡眠质量变化",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "progress"})

        self.assertEqual(result["format"], "progress")
        self.assertIn("topics", result)
        self.assertIn("topic_changes", result)
        self.assertIn("ongoing_themes", result)
        self.assertIn("turn_count", result)

    def test_summarize_session_defaults_to_brief_format(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "你好", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "你好！今天想聊些什么呢？", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
            ],
            last_summary="用户发起了对话",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({})

        self.assertEqual(result["format"], "brief")
        self.assertIn("turn_count", result)

    def test_summarize_session_empty_recent_messages_returns_minimal_output(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "detailed"})

        self.assertEqual(result["format"], "detailed")
        self.assertEqual(result["turn_count"], 0)
        self.assertEqual(result["topics"], [])
        self.assertIn("source", result)
        self.assertEqual(result["source"], "conversation_state")

    def test_summarize_session_extracts_suggestions_from_assistant_messages(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "我太累了", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
                {"id": "m2", "role": "assistant", "content": "我建议你给自己一些休息的时间，不妨试试每天安排半小时的安静时间。你可以试试正念冥想来帮助放松。", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:05"},
            ],
            last_summary="用户表达了疲惫",
        )
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["summarize_session"]({"format": "detailed"})

        self.assertIn("suggestions_given", result)
        self.assertIsInstance(result["suggestions_given"], list)
        self.assertGreater(len(result["suggestions_given"]), 0)

    def test_summarize_session_records_preview(self) -> None:
        state = make_state(
            recent_messages=[
                {"id": "m1", "role": "user", "content": "帮我总结一下", "input_type": "text", "risk_level": "L0", "metadata": {}, "created_at": "2026-05-12T10:00:00"},
            ],
            last_summary="用户请求总结",
        )
        plan = build_dialogue_tool_plan(state)

        plan.tool_handlers["summarize_session"]({"format": "detailed"})

        previews = plan.audit_capture.previews
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["name"], "summarize_session")
        self.assertEqual(previews[0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
