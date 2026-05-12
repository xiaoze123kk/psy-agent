from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.graphs.nodes.memory_nodes import summarize_turn
from app.graphs.nodes.response_nodes import companion_response
from app.graphs.state import AgentState
from app.services.deepseek_client import ToolChatResult


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

