from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.graphs.nodes.memory_nodes import memory_candidate_extract, summarize_turn
from app.graphs.nodes.response_nodes import companion_response
from app.graphs.state import AgentState
from app.services.deepseek_client import ToolChatResult, deepseek_client


def _run(coro):
    return asyncio.run(coro)


class ResponseMemoryContinuityTests(unittest.TestCase):
    def make_state(self, **overrides) -> AgentState:
        state: AgentState = {
            "user_text": "一想到老师就烦",
            "normalized_text": "一想到老师就烦",
            "input_type": "text",
            "user_mode": "teen",
            "intent": "other",
            "risk_level": "L0",
            "risk_reasons": [],
            "messages": [],
            "recent_messages": [],
            "last_summary": "上次主要在聊最近在意的困扰：烦死了；下次可以从最卡住的那一刻接着展开。",
            "profile": {"user_mode": "teen", "nickname": "test_user"},
            "companion_preferences": {"style": "gentle", "question_tolerance": "low"},
            "memory_mode": "summary_only",
            "retrieved_memories": [],
            "assistant_text": "",
            "suggested_actions": [],
            "session_summary": "",
            "memory_candidates": [],
            "should_write_memory": False,
            "audit_tags": [],
        }
        state.update(overrides)
        return state

    def test_companion_empty_model_returns_no_reply(self) -> None:
        state = self.make_state()
        with (
            patch("app.graphs.nodes.rag_nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[])),
            patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value="")),
        ):
            result = _run(companion_response(state))

        self.assertEqual(result["assistant_text"], "")
        self.assertEqual(result["suggested_actions"], [])

    def test_companion_empty_model_does_not_use_contextual_template(self) -> None:
        state = self.make_state(
            normalized_text="那条街有太多回忆了",
            user_text="那条街有太多回忆了",
            last_summary="",
            intent="other",
            recent_messages=[],
        )
        with (
            patch("app.graphs.nodes.rag_nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[])),
            patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value="")),
        ):
            result = _run(companion_response(state))

        assistant_text = result["assistant_text"]
        self.assertEqual(assistant_text, "")
        self.assertEqual(result["suggested_actions"], [])

    def test_summarize_turn_uses_neutral_internal_summary(self) -> None:
        result = _run(summarize_turn(self.make_state(normalized_text="烦死了", intent="other")))

        summary = result["session_summary"]
        self.assertIn("本轮主题", summary)
        self.assertNotIn("上次主要在聊", summary)
        self.assertNotIn("下次可以从", summary)

    def test_summarize_turn_updates_session_digest_from_llm(self) -> None:
        llm_digest = {
            "key_themes": ["职场压力", "任务安排", "睡眠疲惫"],
            "emotional_arc": "紧绷 -> 疲惫 -> 稍微松动",
            "effective_interventions": ["先共情再轻量梳理"],
            "ineffective_interventions": ["直接给建议"],
            "unresolved_threads": ["和主管沟通任务边界"],
            "significant_changes": ["用户提到沟通后稍微轻松"],
            "last_updated_turn": 3,
            "summary_200chars": "用户延续职场压力主题，谈到与主管沟通任务安排后稍微轻松，但仍有疲惫和睡眠困扰。",
        }
        state = self.make_state(
            normalized_text="今天和主管谈了任务安排后，稍微轻松一点，但还是很累。",
            assistant_text="你已经做了一次很重要的沟通，现在身体还在慢慢卸力。",
            intent="light_counseling",
            session_digest={
                "key_themes": ["职场压力"],
                "emotional_arc": "紧绷 -> 疲惫",
                "unresolved_threads": ["任务安排"],
                "last_updated_turn": 2,
                "summary_200chars": "用户近期在聊职场压力和任务安排。",
            },
        )

        with patch.object(deepseek_client, "chat", new=AsyncMock(return_value=json.dumps(llm_digest, ensure_ascii=False))):
            result = _run(summarize_turn(state))

        digest = result["session_digest"]
        self.assertEqual(digest["schema_version"], 1)
        self.assertEqual(digest["key_themes"], ["职场压力", "任务安排", "睡眠疲惫"])
        self.assertEqual(digest["last_updated_turn"], 3)
        self.assertEqual(digest["summary_200chars"], llm_digest["summary_200chars"])
        self.assertEqual(result["session_summary"], llm_digest["summary_200chars"])

    def test_summarize_turn_keeps_existing_digest_when_llm_json_invalid(self) -> None:
        existing_digest = {
            "key_themes": ["关系压力"],
            "summary_200chars": "用户最近在聊关系压力。",
        }
        state = self.make_state(
            normalized_text="我还是不知道怎么和朋友说",
            intent="light_counseling",
            session_digest=existing_digest,
        )

        with patch.object(deepseek_client, "chat", new=AsyncMock(return_value="不是 JSON")):
            result = _run(summarize_turn(state))

        self.assertEqual(result["session_digest"], existing_digest)
        self.assertIn("本轮主题", result["session_summary"])

    def test_summarize_turn_sanitizes_and_trims_digest_fields(self) -> None:
        state = self.make_state(
            normalized_text="我的邮箱是 test@example.com，电话 13812345678，最近工作压力很大。",
            assistant_text="我会只保留对连续性有用的概括。",
        )
        llm_digest = {
            "key_themes": ["职场压力", "睡眠", "关系", "自我要求", "边界", "额外主题"],
            "emotional_arc": "焦虑" * 80,
            "effective_interventions": ["先听再回应"] * 8,
            "ineffective_interventions": [],
            "unresolved_threads": ["联系 test@example.com 或 13812345678"] * 3,
            "significant_changes": ["用户给出了手机号 13812345678"],
            "last_updated_turn": 1,
            "summary_200chars": "用户邮箱 test@example.com，电话 13812345678。" + ("工作压力仍在延续。" * 30),
        }

        with patch.object(deepseek_client, "chat", new=AsyncMock(return_value=json.dumps(llm_digest, ensure_ascii=False))):
            result = _run(summarize_turn(state))

        digest = result["session_digest"]
        self.assertEqual(len(digest["key_themes"]), 5)
        self.assertLessEqual(len(digest["effective_interventions"]), 5)
        self.assertLessEqual(len(digest["summary_200chars"]), 200)
        serialized = json.dumps(digest, ensure_ascii=False)
        self.assertNotIn("test@example.com", serialized)
        self.assertNotIn("13812345678", serialized)

    def test_summarize_turn_failed_no_reply_does_not_update_session_digest(self) -> None:
        existing_digest = {"key_themes": ["旧主题"], "summary_200chars": "旧摘要"}
        state = self.make_state(delivery_status="failed_no_reply", session_digest=existing_digest)

        with patch.object(deepseek_client, "chat", new=AsyncMock(return_value=json.dumps({"key_themes": ["新主题"]}, ensure_ascii=False))) as chat:
            result = _run(summarize_turn(state))

        chat.assert_not_called()
        self.assertEqual(result["session_summary"], "")
        self.assertEqual(result["session_digest"], existing_digest)

    def test_summarize_turn_skips_llm_for_trivial_followup_when_digest_exists(self) -> None:
        existing_digest = {
            "key_themes": ["职场压力"],
            "summary_200chars": "用户最近在聊职场压力和任务安排。",
        }
        state = self.make_state(
            normalized_text="嗯",
            assistant_text="嗯",
            session_digest=existing_digest,
            session_summary="",
        )

        with patch.object(deepseek_client, "chat", new=AsyncMock(return_value="不会被调用")) as chat:
            result = _run(summarize_turn(state))

        chat.assert_not_called()
        self.assertEqual(result["session_digest"], existing_digest)
        self.assertIn("本轮主题", result["session_summary"])

    def test_memory_candidate_extract_uses_session_digest_for_long_term_candidates(self) -> None:
        state = self.make_state(
            normalized_text="还是卡在这里",
            memory_mode="long_term",
            session_summary="用户继续讨论职场压力。",
            session_digest={
                "key_themes": ["职场压力", "任务边界"],
                "effective_interventions": ["先共情再轻量梳理"],
                "unresolved_threads": ["如何和主管开口"],
                "significant_changes": ["用户已经尝试整理任务清单"],
                "summary_200chars": "用户持续讨论职场压力和任务边界。",
            },
        )

        result = _run(memory_candidate_extract(state))

        candidates = result["memory_candidates"]
        candidate_types = [candidate["memory_type"] for candidate in candidates]
        serialized = json.dumps(candidates, ensure_ascii=False)
        self.assertIn("session_summary", candidate_types)
        self.assertIn("state", candidate_types)
        self.assertIn("support_strategy", candidate_types)
        self.assertIn("recurring_trigger", candidate_types)
        self.assertIn("职场压力", serialized)
        self.assertIn("先共情再轻量梳理", serialized)
        self.assertIn("如何和主管开口", serialized)

    def test_memory_candidate_extract_creates_correction_candidate_for_explicit_feedback(self) -> None:
        state = self.make_state(
            normalized_text="不要一上来就分析，先听我说完，再给建议。",
            memory_mode="long_term",
            session_summary="用户明确纠正陪伴方式，希望先被倾听。",
        )

        result = _run(memory_candidate_extract(state))

        candidates = result["memory_candidates"]
        correction = next(candidate for candidate in candidates if candidate["memory_type"] == "correction")
        self.assertIn("先听我说完", correction["content"])
        self.assertGreaterEqual(correction["importance"], 4)
        self.assertIn("纠错", correction["tags"])

    def test_memory_candidate_extract_creates_goal_candidate_for_explicit_goal(self) -> None:
        state = self.make_state(
            normalized_text="我想先把和主管沟通任务边界这件事理清楚。",
            memory_mode="long_term",
            session_summary="用户表达了当前想处理的工作沟通目标。",
        )

        result = _run(memory_candidate_extract(state))

        candidates = result["memory_candidates"]
        goal = next(candidate for candidate in candidates if candidate["memory_type"] == "goal")
        self.assertIn("主管沟通任务边界", goal["content"])
        self.assertGreaterEqual(goal["importance"], 4)
        self.assertIn("目标", goal["tags"])

    def test_memory_candidate_extract_does_not_use_digest_when_summary_only(self) -> None:
        state = self.make_state(
            memory_mode="summary_only",
            session_summary="用户继续讨论职场压力。",
            session_digest={
                "key_themes": ["职场压力"],
                "effective_interventions": ["先共情再轻量梳理"],
                "unresolved_threads": ["如何和主管开口"],
            },
        )

        result = _run(memory_candidate_extract(state))

        self.assertEqual([candidate["memory_type"] for candidate in result["memory_candidates"]], ["session_summary"])

    def test_companion_reply_uses_multi_turn_messages(self) -> None:
        captured_messages: list[dict[str, str]] = []
        state = self.make_state(
            normalized_text="我还是很累",
            recent_messages=[
                {"role": "user", "content": "最近工作一直压着我"},
                {"role": "assistant", "content": "那种被工作追着跑的感觉，确实会很耗。"},
            ],
        )

        async def fake_chat(messages):
            captured_messages.extend(messages)
            return "我听见这个“还是”，像是那股累并没有真的退下去。\n---\n继续说说"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)):
            result = _run(companion_response(state))

        self.assertEqual(result["assistant_text"], "我听见这个“还是”，像是那股累并没有真的退下去。")
        self.assertEqual([message["role"] for message in captured_messages[:3]], ["system", "user", "assistant"])
        self.assertEqual(captured_messages[1]["content"], "最近工作一直压着我")
        self.assertEqual(captured_messages[2]["content"], "那种被工作追着跑的感觉，确实会很耗。")
        self.assertEqual(captured_messages[-1]["role"], "user")
        self.assertIn("用户刚刚说：我还是很累", captured_messages[-1]["content"])

    def test_companion_reply_trims_recent_messages_by_budget(self) -> None:
        captured_messages: list[dict[str, str]] = []
        long_history = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"旧消息{index}-" + ("很长的背景。" * 120),
            }
            for index in range(18)
        ]
        state = self.make_state(
            normalized_text="我现在还是卡在沟通这一步",
            recent_messages=[
                *long_history,
                {"role": "user", "content": "最近一直在聊任务边界"},
                {"role": "assistant", "content": "你在试着把责任和界限分清楚。"},
                {"role": "user", "content": "我现在还是卡在沟通这一步"},
            ],
        )

        async def fake_chat(messages):
            captured_messages.extend(messages)
            return "这次卡住的点还是和任务边界有关。\n---\n继续说沟通"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)):
            _run(companion_response(state))

        history_messages = captured_messages[1:-1]
        history_text = "\n".join(message["content"] for message in history_messages)
        self.assertLessEqual(sum(len(message["content"]) for message in history_messages), 1800)
        self.assertNotIn("旧消息0-", history_text)
        self.assertIn("最近一直在聊任务边界", history_text)
        self.assertIn("你在试着把责任和界限分清楚。", history_text)
        self.assertEqual(captured_messages[-1]["role"], "user")
        self.assertIn("用户刚刚说：我现在还是卡在沟通这一步", captured_messages[-1]["content"])
        self.assertNotIn("我现在还是卡在沟通这一步", history_text)

    def test_tool_reply_uses_multi_turn_messages(self) -> None:
        captured_messages: list[dict[str, str]] = []
        state = self.make_state(
            normalized_text="我还是睡不好",
            tooling_enabled=True,
            recent_messages=[
                {"role": "user", "content": "昨晚又醒了好几次"},
                {"role": "assistant", "content": "这种反复醒来的疲惫会一直拖到白天。"},
            ],
        )

        async def fake_chat_with_tools(messages, **kwargs):
            captured_messages.extend(messages)
            return ToolChatResult(
                content="这次的“还是”更像是在延续昨晚反复醒来的困扰。\n---\n说说昨晚",
                tool_events=[],
                finish_reason="stop",
                messages=messages,
            )

        with patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(side_effect=fake_chat_with_tools),
        ):
            result = _run(companion_response(state))

        self.assertEqual(result["assistant_text"], "这次的“还是”更像是在延续昨晚反复醒来的困扰。")
        self.assertEqual([message["role"] for message in captured_messages[:3]], ["system", "user", "assistant"])
        self.assertEqual(captured_messages[1]["content"], "昨晚又醒了好几次")
        self.assertEqual(captured_messages[2]["content"], "这种反复醒来的疲惫会一直拖到白天。")
        self.assertEqual(captured_messages[-1]["role"], "user")
        self.assertIn("用户刚刚说：我还是睡不好", captured_messages[-1]["content"])

    def test_tool_reply_uses_budgeted_recent_messages(self) -> None:
        captured_messages: list[dict[str, str]] = []
        state = self.make_state(
            normalized_text="还是睡前最容易反复想",
            tooling_enabled=True,
            recent_messages=[
                *[
                    {
                        "role": "user" if index % 2 == 0 else "assistant",
                        "content": f"很早之前的睡眠背景{index}-" + ("反复铺垫。" * 120),
                    }
                    for index in range(18)
                ],
                {"role": "user", "content": "昨晚睡前又开始反刍"},
                {"role": "assistant", "content": "睡前安静下来时，那些念头就更容易冒出来。"},
            ],
        )

        async def fake_chat_with_tools(messages, **kwargs):
            captured_messages.extend(messages)
            return ToolChatResult(
                content="睡前反刍像是这条线一直在延续。\n---\n说说睡前",
                tool_events=[],
                finish_reason="stop",
                messages=messages,
            )

        with patch(
            "app.services.tooling.deepseek_client.chat_with_tools",
            new=AsyncMock(side_effect=fake_chat_with_tools),
        ):
            _run(companion_response(state))

        history_messages = captured_messages[1:-1]
        history_text = "\n".join(message["content"] for message in history_messages)
        self.assertLessEqual(sum(len(message["content"]) for message in history_messages), 1800)
        self.assertNotIn("很早之前的睡眠背景0-", history_text)
        self.assertIn("昨晚睡前又开始反刍", history_text)
        self.assertIn("睡前安静下来时，那些念头就更容易冒出来。", history_text)

