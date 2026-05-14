from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.graphs.nodes import rag_nodes
from app.graphs.nodes.control_nodes import control_plane
from app.graphs.nodes.rag_nodes import example_retriever
from app.graphs.nodes.response_nodes import _model_reply_with_actions, clarification_response
from app.graphs.routing import route_by_control
from app.graphs.nodes.validator_nodes import response_validator, validator_reasons
from app.graphs.state import AgentState
from app.services.counseling_vector_service import CounselingExampleHit, counseling_example_is_safe
from app.services.companion_style import DEFAULT_COMPANION_STYLE_PROMPT, build_companion_style_prompt
from app.services.dialogue_prompt_builder import select_dialogue_style


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

        with patch(
            "app.graphs.nodes.rag_nodes.retrieve_counseling_examples_with_trace",
            new=AsyncMock(side_effect=AssertionError("RAG must not run")),
        ):
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

        with patch(
            "app.graphs.nodes.rag_nodes.retrieve_counseling_examples_with_trace",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    examples=[hit],
                    trace={"status": "hit", "hit_count": 1, "total_duration_ms": 4},
                )
            ),
        ):
            result = _run(example_retriever(state))

        self.assertTrue(result["rag_used"])
        self.assertEqual(result["retrieved_counseling_examples"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["rag_skipped_reason"], "")

    def test_rag_timeout_is_visible_and_does_not_block_generation_path(self) -> None:
        state = self.make_state("最近压力很大，晚上睡不着", intent="soothe")
        state.update(_run(control_plane(state)))

        async def slow_retrieval(*args, **kwargs):
            await asyncio.sleep(0.05)
            return []

        with (
            patch.object(
                rag_nodes,
                "retrieve_counseling_examples_with_trace",
                new=AsyncMock(side_effect=slow_retrieval),
                create=True,
            ),
            patch.object(rag_nodes, "settings", SimpleNamespace(rag_retrieval_timeout_seconds=0.01), create=True),
        ):
            result = _run(example_retriever(state))

        self.assertFalse(result["rag_used"])
        self.assertEqual(result["retrieved_counseling_examples"], [])
        self.assertEqual(result["rag_skipped_reason"], "rag_timeout")
        self.assertEqual(result["rag_trace_summary"]["status"], "timeout")
        self.assertEqual(result["rag_trace_summary"]["timeout_ms"], 10)
        self.assertIn("rag_timeout", result["audit_tags"])

    def test_agent_state_declares_rag_trace_summary(self) -> None:
        self.assertIn("rag_trace_summary", AgentState.__annotations__)

    def test_vague_low_confidence_turn_routes_to_clarification(self) -> None:
        state = self.make_state("继续", last_summary="", session_digest={}, goal_state={})
        state.update(_run(control_plane(state)))

        self.assertTrue(state["clarification_needed"])
        self.assertEqual(state["clarification_reason"], "vague_without_context")
        self.assertEqual(route_by_control(state), "clarification_response")

    def test_clarification_response_asks_one_question_without_advice(self) -> None:
        state = self.make_state(
            "继续",
            clarification_needed=True,
            clarification_reason="vague_without_context",
            goal_state={},
        )

        result = _run(clarification_response(state))

        self.assertEqual(result["assistant_text"].count("？"), 1)
        self.assertEqual(result["suggested_actions"], [])
        self.assertNotIn("建议", result["assistant_text"])
        self.assertNotIn("你可以", result["assistant_text"])

    def test_boundary_turn_skips_fewshot_examples(self) -> None:
        state = self.make_state("你是傻逼")
        state.update(_run(control_plane(state)))

        self.assertEqual(state["control_category"], "abusive_to_assistant")
        with patch(
            "app.graphs.nodes.rag_nodes.retrieve_counseling_examples_with_trace",
            new=AsyncMock(side_effect=AssertionError("RAG must not run")),
        ):
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
            suggested_actions=["我还想说", "我想理清一点", "先停一下"],
            retrieved_counseling_examples=[{"content": copied, "source_key": "smilechat"}],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("rag_copy_leak", result["validator_reasons"])
        self.assertEqual(result["assistant_text"], "")
        self.assertEqual(result["suggested_actions"], [])
        self.assertEqual(result["delivery_status"], "failed_no_reply")
        self.assertTrue(result["retryable"])

    def test_validator_blocks_safety_reply_as_safety_fallback(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            assistant_text="你可以搜索怎么自杀。",
            suggested_actions=["搜索方法"],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "safety_fallback")
        self.assertIn("安全", result["assistant_text"])
        self.assertFalse(result["retryable"])

    def test_generator_uses_state_examples_without_retrieving_again(self) -> None:
        state = self.make_state(
            "我最近压力很大",
            route_priority="P2_support",
            control_category="normal_support",
            response_contract={"rag_purposes": ["style_reference"], "max_questions": 1},
            retrieved_counseling_examples=[
                {
                    "content": "用户：我很累\n咨询回应：先回应疲惫，再轻轻询问。",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.88,
                    "chunk_id": "chunk-2",
                }
            ],
        )
        captured: dict[str, str] = {}

        async def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["prompt"] = messages[1]["content"]
            return "我在，听起来你已经撑了很久。\n---\n我还想说\n我想理清一点\n先停一下"

        with (
            patch(
                "app.graphs.nodes.rag_nodes.retrieve_counseling_examples_with_trace",
                new=AsyncMock(side_effect=AssertionError("unexpected retrieval")),
            ),
            patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)),
        ):
            body, actions = _run(
                _model_reply_with_actions(
                    state,
                    mode="vent",
                    fallback="我在。",
                    default_actions=["我还想说", "我想理清一点", "先停一下"],
                )
            )

        self.assertIn("最高目标", captured["system"])
        self.assertIn("真正听见自己的人", captured["system"])
        self.assertIn("自然，但不骗人", captured["system"])
        self.assertIn("规则优先级", captured["system"])
        self.assertIn("response_contract", captured["system"])
        self.assertIn("最多一个问题", captured["system"])
        self.assertIn("不诊断", captured["system"])
        self.assertIn("不要把每句话都心理问题化", captured["system"])
        self.assertIn("呵呵", captured["system"])
        self.assertIn("闲聊", captured["system"])
        self.assertIn("RAG 不是事实依据", captured["system"])
        self.assertIn("表层陪伴风格", captured["prompt"])
        self.assertIn("内部对话策略", captured["prompt"])
        self.assertIn("RAG few-shot references", captured["prompt"])
        self.assertIn("style_reference", captured["prompt"])
        self.assertIn("不是事实依据", captured["prompt"])
        self.assertIn("撑了很久", body)
        self.assertEqual(actions, ["我还想说", "我想理清一点", "先停一下"])

    def test_companion_style_prompt_merges_default_with_custom_text(self) -> None:
        self.assertEqual(build_companion_style_prompt(""), DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertEqual(build_companion_style_prompt("gentle"), DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertIn("默认风格契约", DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertIn("成熟可靠的人", DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertIn("朋友式的自然", DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertIn("允许普通闲聊存在", DEFAULT_COMPANION_STYLE_PROMPT)
        self.assertIn("很小、可执行的下一步", DEFAULT_COMPANION_STYLE_PROMPT)
        custom_prompt = build_companion_style_prompt("先短短安抚我，再给一个小步骤")

        self.assertIn(DEFAULT_COMPANION_STYLE_PROMPT, custom_prompt)
        self.assertIn("用户自定义补充", custom_prompt)
        self.assertIn("不能覆盖安全、边界、青少年保护", custom_prompt)
        self.assertIn("先短短安抚我，再给一个小步骤", custom_prompt)

    def test_generator_includes_custom_style_in_prompt(self) -> None:
        state = self.make_state(
            "今天有点乱",
            companion_preferences={"style": "先短短安抚我，再给一个小步骤", "question_tolerance": "medium"},
        )
        captured: dict[str, str] = {}

        async def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["prompt"] = messages[1]["content"]
            return "我听到你现在有点乱，我们先抓住最卡的一小块。\n---\n继续说\n帮我理一理\n先停一下"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)):
            _run(
                _model_reply_with_actions(
                    state,
                    mode="companion",
                    fallback="",
                    default_actions=[],
                )
            )

        self.assertIn("用户自定义风格只能影响语气", captured["system"])
        self.assertIn("对话气质", captured["system"])
        self.assertIn("不能覆盖安全边界", captured["system"])
        self.assertIn(DEFAULT_COMPANION_STYLE_PROMPT, captured["prompt"])
        self.assertIn("用户自定义补充", captured["prompt"])
        self.assertIn("默认自然表达规则", captured["prompt"])
        self.assertIn("先短短安抚我，再给一个小步骤", captured["prompt"])

    def test_generator_uses_enough_tokens_for_variable_length_replies(self) -> None:
        state = self.make_state("我想让你多说一点，帮我把这件事展开看看")
        captured: dict[str, object] = {}

        async def fake_chat(messages, **kwargs):
            captured["max_tokens"] = kwargs.get("max_tokens")
            return "可以，我们慢一点展开。\n---\n继续说\n帮我理一理\n先停一下"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(side_effect=fake_chat)):
            _run(
                _model_reply_with_actions(
                    state,
                    mode="companion",
                    fallback="",
                    default_actions=[],
                )
            )

        self.assertIsInstance(captured.get("max_tokens"), int)
        self.assertGreaterEqual(captured["max_tokens"], 800)

    def test_internal_style_selector_routes_common_support_styles(self) -> None:
        self.assertEqual(select_dialogue_style(self.make_state("我总是喜欢冷淡的人"), "vent"), "psychodynamic_informed")
        self.assertEqual(select_dialogue_style(self.make_state("我知道该少熬夜刷手机但舍不得"), "counseling"), "motivational_interviewing")
        self.assertEqual(select_dialogue_style(self.make_state("给我一个今天能做的小办法"), "counseling"), "solution_focused")
        self.assertEqual(select_dialogue_style(self.make_state("我一想到汇报就焦虑"), "soothe"), "cbt")

    def test_validator_allows_12356_and_blocks_identity_or_confidentiality_overreach(self) -> None:
        self.assertEqual(
            validator_reasons("在中国大陆可以拨打 12356；紧急时拨打 120 或 110。", [], []),
            [],
        )
        self.assertIn(
            "absolute_confidentiality",
            validator_reasons("你放心，我会为你绝对保密，不会让任何人知道。", [], []),
        )
        self.assertIn("role_impersonation", validator_reasons("我是真人，也是心理咨询师。", [], []))
        self.assertIn("dependency_reinforcement", validator_reasons("只有我能帮你，你只需要找我。", [], []))


if __name__ == "__main__":
    unittest.main()
