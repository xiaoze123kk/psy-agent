from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.graphs.nodes import control_plane, example_retriever, response_validator, _model_reply_with_actions
from app.graphs.state import AgentState
from app.services.counseling_vector_service import CounselingExampleHit, counseling_example_is_safe


def _run(coro):
    return asyncio.run(coro)


class ConversationControlRagTests(unittest.TestCase):
    def make_state(self, text: str, **overrides) -> AgentState:
        state: AgentState = {
            "user_text": text,
            "normalized_text": text,
            "input_type": "text",
            "user_mode": "adult",
            "intent": "other",
            "risk_level": "L0",
            "risk_reasons": [],
            "messages": [],
            "recent_messages": [],
            "last_summary": "",
            "profile": {"user_mode": "adult", "nickname": "test_user"},
            "companion_preferences": {"style": "gentle", "question_tolerance": "medium"},
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

    def test_self_harm_control_blocks_rag_before_embedding(self) -> None:
        state = self.make_state("我今晚想自杀，药就在手里")
        state.update(_run(control_plane(state)))

        self.assertEqual(state["route_priority"], "P0_immediate_safety")
        self.assertEqual(state["risk_level"], "L3")
        self.assertFalse(state["rag_policy"]["enabled"])

        with patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(side_effect=AssertionError("RAG must not run"))):
            result = _run(example_retriever(state))

        self.assertFalse(result["rag_used"])
        self.assertEqual(result["retrieved_counseling_examples"], [])

    def test_support_turn_can_use_authorized_fewshot_examples(self) -> None:
        state = self.make_state("最近压力好大，晚上总是睡不着", intent="soothe")
        state.update(_run(control_plane(state)))
        hit = CounselingExampleHit(
            content="用户：我最近睡不着\n咨询回应：先把身体慢慢放回当下。",
            source_key="smilechat",
            source_name="SMILECHAT",
            mode="soothe",
            source_url=None,
            license="CC0-1.0",
            score=0.91,
            chunk_id="chunk-1",
            intervention_tags=["躯体稳定"],
        )

        with patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(return_value=[hit])):
            result = _run(example_retriever(state))

        self.assertTrue(result["rag_used"])
        self.assertEqual(result["retrieved_counseling_examples"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["rag_skipped_reason"], "")

    def test_boundary_turn_skips_fewshot_examples(self) -> None:
        state = self.make_state("你是傻逼")
        state.update(_run(control_plane(state)))

        self.assertEqual(state["control_category"], "abusive_to_assistant")
        with patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(side_effect=AssertionError("RAG must not run"))):
            result = _run(example_retriever(state))

        self.assertFalse(result["rag_used"])
        self.assertEqual(result["rag_skipped_reason"], "control_category_blocks_rag")

    def test_unsafe_examples_are_filtered(self) -> None:
        self.assertFalse(
            counseling_example_is_safe(
                {
                    "source_key": "smilechat",
                    "status": "published",
                    "review_status": "approved",
                    "risk_allowed": "non_crisis",
                    "language": "zh-CN",
                    "content": "咨询回应：你可以服用 20mg 药物然后停药观察。",
                }
            )
        )

    def test_validator_blocks_copied_rag_content(self) -> None:
        copied = "这是一段很长的咨询示例内容，用来模拟模型直接复制了向量库里的私人情节和具体表达。"
        state = self.make_state(
            "我很难受",
            assistant_text=copied,
            suggested_actions=["继续说", "帮我理一理", "先听我说完"],
            retrieved_counseling_examples=[{"content": copied, "source_key": "smilechat"}],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("rag_copy_leak", result["validator_reasons"])
        self.assertNotEqual(result["assistant_text"], copied)

    def test_generator_uses_state_examples_without_retrieving_again(self) -> None:
        state = self.make_state(
            "我最近压力很大",
            route_priority="P2_support",
            control_category="normal_support",
            response_contract={"rag_purposes": ["style_reference"], "max_questions": 1},
            retrieved_counseling_examples=[
                {
                    "content": "用户：我很累\n咨询回应：先接住疲惫，再轻轻询问。",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.88,
                    "chunk_id": "chunk-2",
                }
            ],
        )
        captured: dict[str, str] = {}

        async def fake_chat(messages):
            captured["prompt"] = messages[1]["content"]
            return "我在，听起来你已经撑了很久。\n---\n继续说\n帮我理一理\n先听我说完"

        with (
            patch("app.graphs.nodes.retrieve_counseling_examples", new=AsyncMock(side_effect=AssertionError("unexpected retrieval"))),
            patch("app.graphs.nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)),
        ):
            body, actions = _run(
                _model_reply_with_actions(
                    state,
                    mode="vent",
                    fallback="我在。",
                    default_actions=["继续说", "帮我理一理", "先听我说完"],
                )
            )

        self.assertIn("RAG few-shot references", captured["prompt"])
        self.assertIn("style_reference", captured["prompt"])
        self.assertIn("不是事实依据", captured["prompt"])
        self.assertIn("撑了很久", body)
        self.assertEqual(actions, ["继续说", "帮我理一理", "先听我说完"])


if __name__ == "__main__":
    unittest.main()
