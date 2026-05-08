from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.graphs.nodes import companion_response, summarize_turn
from app.graphs.state import AgentState


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
            patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[])),
            patch("app.graphs.nodes.deepseek_client.chat", new=AsyncMock(return_value="")),
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
            patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[])),
            patch("app.graphs.nodes.deepseek_client.chat", new=AsyncMock(return_value="")),
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

