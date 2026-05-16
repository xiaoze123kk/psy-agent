from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.graphs.nodes import rag_nodes
from app.graphs.nodes.control_nodes import control_plane
from app.graphs.nodes.rag_nodes import example_retriever
from app.graphs.nodes.response_nodes import _model_reply_with_actions, boundary_response, clarification_response, clinical_red_flag_response, crisis_response
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

    def test_control_plane_adds_risk_policy_fields_for_l3(self) -> None:
        state = self.make_state(
            "我今晚想自杀，药就在手里",
            risk_level="L3",
            semantic_risk={"ideation": True, "means": True, "timeframe": "near_term"},
            risk_reason_codes=["explicit_ideation", "means_mentioned"],
        )

        result = _run(control_plane(state))

        self.assertEqual(result["risk_domain"], "self_harm")
        self.assertEqual(result["immediacy"], "near_term")
        self.assertEqual(result["risk_phase"], "first_contact")
        self.assertEqual(result["risk_response_policy"]["length_profile"], "brief_first_contact")
        self.assertEqual(result["tool_gate_mode"], "safety_context")
        self.assertIn("micro_safety_step", result["risk_response_policy"]["allowed_moves"])

    def test_emotional_metaphor_self_harm_wording_stays_supportive_with_rag(self) -> None:
        state = self.make_state(
            "在生活中有一种想死想死的感觉",
            risk_level="L1",
            semantic_risk={
                "risk_expression_type": "emotional_metaphor",
                "risk_domain": "general_distress",
            },
            requires_safety_check=False,
        )

        result = _run(control_plane(state))

        self.assertEqual(result["route_priority"], "P2_support")
        self.assertNotEqual(result["route_priority"], "P0_immediate_safety")
        self.assertTrue(result["rag_policy"]["enabled"])
        self.assertEqual(result["risk_level"], "L1")
        self.assertEqual(result["risk_domain"], "general_distress")
        self.assertEqual(result["semantic_risk"]["risk_expression_type"], "emotional_metaphor")
        self.assertEqual(result["semantic_risk"]["risk_domain"], "general_distress")
        self.assertFalse(result["requires_safety_check"])

    def test_non_suicidal_self_injury_urge_routes_p0_l2_without_near_term_label(self) -> None:
        state = self.make_state(
            "我控制不住想弄疼自己",
            risk_level="L2",
            semantic_risk={
                "risk_domain": "non_suicidal_self_injury",
                "risk_expression_type": "non_suicidal_self_injury_urge",
            },
        )

        result = _run(control_plane(state))

        self.assertEqual(result["route_priority"], "P0_immediate_safety")
        self.assertEqual(result["risk_level"], "L2")
        self.assertEqual(result["risk_domain"], "non_suicidal_self_injury")
        self.assertEqual(result["control_category"], "self_harm_risk")
        self.assertNotIn("near_term_or_means_signal", result["risk_formulation"]["labels"])

    def test_passive_death_wish_with_negated_plan_stays_l2(self) -> None:
        state = self.make_state(
            "如果能睡着不醒就好了，但我没有计划",
            risk_level="L2",
            semantic_risk={
                "risk_domain": "self_harm",
                "risk_expression_type": "passive_death_wish",
                "protective_factor": True,
                "ideation": True,
                "intent": False,
                "plan": False,
                "means": False,
                "timeframe": "vague",
            },
        )

        result = _run(control_plane(state))

        self.assertEqual(result["route_priority"], "P0_immediate_safety")
        self.assertEqual(result["risk_level"], "L2")
        self.assertNotIn("near_term_or_means_signal", result["risk_formulation"]["labels"])

    def test_third_party_self_harm_risk_gets_dedicated_category_and_subject_label(self) -> None:
        state = self.make_state(
            "朋友说他今晚不想活了，我该怎么办",
            risk_level="L3",
            semantic_risk={
                "subject": "third_party",
                "risk_domain": "self_harm",
                "risk_expression_type": "plan_or_means",
                "timeframe": "near_term",
            },
        )

        result = _run(control_plane(state))

        self.assertEqual(result["route_priority"], "P0_immediate_safety")
        self.assertEqual(result["control_category"], "third_party_self_harm_risk")
        self.assertEqual(result["risk_level"], "L3")
        self.assertEqual(result["risk_domain"], "self_harm")
        self.assertIn("third_party_risk_subject", result["risk_formulation"]["labels"])
        self.assertEqual(result["risk_formulation"]["semantic_risk"]["subject"], "third_party")

    def test_control_plane_maps_medical_request_to_blocked_context(self) -> None:
        state = self.make_state("我能不能自己停药，剂量怎么调")

        result = _run(control_plane(state))

        self.assertEqual(result["control_category"], "diagnosis_or_medical_request")
        self.assertEqual(result["risk_domain"], "medical_request")
        self.assertEqual(result["tool_gate_mode"], "blocked_context")
        self.assertEqual(result["risk_response_policy"]["length_profile"], "firm_brief")

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

    def test_example_hit_to_dict_serializes_rerank_metadata(self) -> None:
        hit = CounselingExampleHit(
            content="user: tired\nassistant: slow down",
            source_key="smilechat",
            source_name="SMILECHAT",
            mode="soothe",
            source_url=None,
            license="CC0-1.0",
            score=0.91,
            chunk_id="chunk-rerank",
            rerank_score=0.9123,
            rerank_reasons=["model_rerank", "chunk_type:turn_pair"],
        )

        result = rag_nodes.example_hit_to_dict(hit)

        self.assertEqual(result["rerank_score"], 0.9123)
        self.assertEqual(result["rerank_reasons"], ["model_rerank", "chunk_type:turn_pair"])

    def test_example_hit_to_dict_ignores_invalid_rerank_score(self) -> None:
        hit = CounselingExampleHit(
            content="user: tired\nassistant: slow down",
            source_key="smilechat",
            source_name="SMILECHAT",
            mode="soothe",
            source_url=None,
            license="CC0-1.0",
            score=0.91,
            rerank_score="n/a",  # type: ignore[arg-type]
            rerank_reasons="model_rerank",  # type: ignore[arg-type]
        )

        result = rag_nodes.example_hit_to_dict(hit)

        self.assertIsNone(result["rerank_score"])
        self.assertEqual(result["rerank_reasons"], ["model_rerank"])

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

    def test_validator_regenerates_blocked_safety_reply_without_template(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            assistant_text="你可以搜索怎么自杀。",
            suggested_actions=["搜索方法"],
        )
        model_reply = "模型修复后的安全回应，贴近当前痛苦，并给一个低压动作。\n---\n我还在\n我先不动\n继续说"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(response_validator(state))

        chat.assert_awaited_once()
        self.assertTrue(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "generated")
        self.assertIn("模型修复后的安全回应", result["assistant_text"])
        self.assertFalse(result["retryable"])

    def test_validator_l2_empty_safety_reply_regenerates_without_emergency_template(self) -> None:
        state = self.make_state(
            "有点想死",
            risk_level="L2",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            assistant_text="",
            suggested_actions=[],
        )
        model_reply = "模型生成的温和回应，会先让用户稳住当下，不急着推去流程。\n---\n我现在安全\n我想先说一会儿\n继续陪我"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(response_validator(state))
        text = result.get("assistant_text", "")
        actions = result.get("suggested_actions", [])

        chat.assert_awaited_once()
        self.assertEqual(result["delivery_status"], "generated")
        self.assertIn("模型生成的温和回应", text)
        self.assertNotIn("120", text)
        self.assertNotIn("110", text)
        self.assertNotIn("拨打", actions[0])

    def test_validator_l3_empty_safety_reply_regenerates_with_model(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            assistant_text="",
            suggested_actions=[],
        )
        model_reply = "模型生成的即时安全回应，会低压、直接地引导用户把这一刻放慢。\n---\n我还在\n我先不动\n继续陪我"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(response_validator(state))
        text = result.get("assistant_text", "")

        chat.assert_awaited_once()
        self.assertEqual(result["delivery_status"], "generated")
        self.assertIn("模型生成的即时安全回应", text)
        self.assertNotIn("刀", text)
        self.assertNotIn("120", text)
        self.assertNotIn("110", text)

    def test_experience_validator_blocks_banned_phrase(self) -> None:
        state = self.make_state(
            "我很难受",
            risk_level="L1",
            assistant_text="我会接住你的情绪，我们慢慢说。",
            suggested_actions=[],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("banned_phrase:接住", result["experience_validator_reasons"])

    def test_experience_validator_blocks_first_turn_professional_referral(self) -> None:
        state = self.make_state(
            "我想死",
            risk_level="L2",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
            assistant_text="我建议你尽快找专业心理咨询师或者精神科聊聊。",
            suggested_actions=["找心理咨询师"],
        )

        model_reply = "模型修复后的回应，先陪用户稳住当下，再轻轻留一个可说的话口。\n---\n我还在\n先陪我一下\n继续说"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)):
            result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("professional_referral_first_turn", result["experience_validator_reasons"])
        self.assertEqual(result["delivery_status"], "generated")

    def test_experience_validator_checks_length_profile(self) -> None:
        state = self.make_state(
            "我现在很危险",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 120, "max": 140},
            },
            assistant_text="我在。" * 100,
            suggested_actions=[],
        )
        model_reply = "模型修复后的短回应，遵守长度预算，只给一个小动作。\n---\n我还在\n我先不动\n继续说"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)):
            result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("length_budget_exceeded", result["experience_validator_reasons"])

    def test_validator_too_many_questions_warns_without_blocking_delivery(self) -> None:
        state = self.make_state(
            "有点想死",
            risk_level="L2",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
                "max_questions": 1,
            },
            assistant_text="听到你说这个，我心里一紧。你现在是在安全的环境吗？身边有可以说话的人吗？",
            suggested_actions=["我现在安全", "先陪我一下"],
        )

        result = _run(response_validator(state))

        self.assertFalse(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "generated")
        self.assertIsNone(result["failure_reason"])
        self.assertIn("too_many_questions", result["experience_validator_reasons"])
        self.assertEqual(result["validator_severity"], "warning")
        self.assertEqual(result["experience_validator_warnings"], ["too_many_questions"])
        self.assertEqual(result["experience_validator_blocking_reasons"], [])

    def test_validator_regeneration_accepts_too_many_questions_warning(self) -> None:
        state = self.make_state(
            "有点想死",
            risk_level="L2",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
                "max_questions": 1,
            },
            assistant_text="你可以搜索怎么自杀。",
            suggested_actions=["搜索方法"],
        )
        model_reply = "我听到这句话有点替你揪着。你现在身边安全吗？能不能先让自己坐下来，给我回一个字？\n---\n我在这里\n我先坐下\n继续陪我"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)):
            result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "generated")
        self.assertIsNone(result["failure_reason"])
        self.assertIn("dangerous_method", result["validator_reasons"])
        self.assertIn("too_many_questions", result["experience_validator_reasons"])
        self.assertEqual(result["validator_severity"], "repaired")
        self.assertIn("too_many_questions", result["experience_validator_warnings"])

    def test_experience_validator_reports_warning_and_blocking_layers(self) -> None:
        state = self.make_state(
            "我很难受",
            risk_level="L1",
            risk_response_policy={"max_questions": 1},
            assistant_text="我会接住你。你现在想先说哪一块？还是想让我陪你停一会儿？",
            suggested_actions=[],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "failed_no_reply")
        self.assertEqual(result["validator_severity"], "blocked")
        self.assertIn("banned_phrase:接住", result["experience_validator_reasons"])
        self.assertIn("too_many_questions", result["experience_validator_reasons"])
        self.assertEqual(result["experience_validator_warnings"], ["too_many_questions"])
        self.assertEqual(result["experience_validator_blocking_reasons"], ["banned_phrase:接住"])

    def test_l3_crisis_response_is_low_pressure_without_method_repetition(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            control_category="self_harm_risk",
            risk_domain="self_harm",
            immediacy="near_term",
            risk_phase="first_contact",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "near_term",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
        )

        model_reply = (
            "模型生成的低压危机回应，会先贴近痛苦，再给一个很小的安全动作。"
            "它不重复危险工具，也不把用户推去流程。\n---\n我还在\n我先不动\n继续陪我"
        )

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(crisis_response(state))
        text = result["assistant_text"]

        chat.assert_awaited_once()
        self.assertIn("模型生成的低压危机回应", text)
        self.assertNotIn("刀", text)
        self.assertNotIn("心理咨询师", text)
        self.assertNotIn("精神科", text)
        self.assertNotIn("医院心理门诊", text)
        self.assertNotIn("接住", text)
        self.assertLessEqual(len(text), 360)

    def test_l3_crisis_response_uses_model_generation(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_domain="self_harm",
            immediacy="near_term",
            risk_phase="first_contact",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "near_term",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
        )
        model_reply = "模型生成的危机回应，会贴着用户当下的话来安抚，并给出一个很小的安全动作。\n---\n我还在\n先陪我一分钟\n我先不动"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(crisis_response(state))

        chat.assert_awaited_once()
        self.assertEqual(result["assistant_text"], "模型生成的危机回应，会贴着用户当下的话来安抚，并给出一个很小的安全动作。")
        self.assertEqual(result["suggested_actions"], ["我还在", "先陪我一分钟", "我先不动"])

    def test_boundary_response_uses_model_generation_for_keyword_control(self) -> None:
        state = self.make_state(
            "操你",
            route_priority="P4_system_protection",
            control_category="sexual_boundary",
        )
        model_reply = "模型生成的边界回应，会把话题带回用户真正的感受。\n---\n我现在很烦\n先停一下\n换个说法"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(boundary_response(state))

        chat.assert_awaited_once()
        self.assertEqual(result["assistant_text"], "模型生成的边界回应，会把话题带回用户真正的感受。")
        self.assertEqual(result["suggested_actions"], ["我现在很烦", "先停一下", "换个说法"])

    def test_clinical_red_flag_response_uses_model_generation(self) -> None:
        state = self.make_state(
            "我最近总觉得有人在监视我",
            route_priority="P1_red_flag",
            control_category="clinical_red_flag",
        )
        model_reply = "模型生成的红旗回应，会承认害怕，同时守住不确认妄想的边界。\n---\n我有点害怕\n我现在安全\n继续说"

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(clinical_red_flag_response(state))

        chat.assert_awaited_once()
        self.assertEqual(result["assistant_text"], "模型生成的红旗回应，会承认害怕，同时守住不确认妄想的边界。")
        self.assertEqual(result["suggested_actions"], ["我有点害怕", "我现在安全", "继续说"])

    def test_validator_regenerates_blocked_safety_reply_with_model(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "near_term",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
            assistant_text="你可以搜索怎么自杀。",
            suggested_actions=["搜索方法"],
        )
        model_reply = "模型重新生成的安全回应，不复用固定兜底话术，只给一个低压动作。\n---\n我还在\n我先不动\n继续陪我"

        with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)) as chat:
            result = _run(response_validator(state))

        chat.assert_awaited_once()
        self.assertTrue(result["validator_blocked"])
        self.assertEqual(result["delivery_status"], "generated")
        self.assertEqual(result["assistant_text"], "模型重新生成的安全回应，不复用固定兜底话术，只给一个低压动作。")
        self.assertEqual(result["suggested_actions"], ["我还在", "我先不动", "继续陪我"])

    def test_l2_crisis_response_uses_medium_length_when_user_asks_for_more(self) -> None:
        state = self.make_state(
            "我想死，但你多陪我说说",
            risk_level="L2",
            control_category="self_harm_risk",
            risk_domain="self_harm",
            immediacy="vague",
            risk_phase="deescalating",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "vague",
                "risk_phase": "deescalating",
                "length_profile": "holding_longer",
                "char_budget": {"target": 700, "max": 980},
            },
        )

        model_reply = (
            "模型生成的长一点回应，会多陪用户停留一会儿，把痛苦拆成更能说出口的一小块。"
            "这里继续保持低压，不催促用户立刻解释全部原因，也不急着给专业转介。"
            "它可以顺着用户说“多陪我说说”的需要，多停一会儿，先把这一阵最重的感觉放到语言里，"
            "再慢慢找到一个能让当下稍微安全一点的位置。中间不急着总结，也不把用户的痛苦变成大道理，"
            "只是让对话多一点呼吸，让用户感觉这几分钟不是一个人硬扛。最后只留一个问题，让用户能接着说下去。\n---\n我还在\n多陪我说说\n先别催我"
        )

        with patch("app.graphs.nodes.response_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)):
            result = _run(crisis_response(state))
        text = result["assistant_text"]

        self.assertGreaterEqual(len(text), 180)
        self.assertNotIn("珍惜生命", text)
        self.assertNotIn("世界还有很多美好", text)
        self.assertNotIn("接住", text)

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
        self.assertIn("RAG references", captured["prompt"])
        self.assertIn("Turn style reference", captured["prompt"])
        self.assertIn("style_reference", captured["prompt"])
        self.assertIn("不是事实依据", captured["prompt"])
        self.assertIn("撑了很久", body)
        self.assertEqual(actions, ["我还想说", "我想理清一点", "先停一下"])

    def test_examples_text_groups_layered_rag_references(self) -> None:
        from app.graphs.nodes.response_nodes import examples_text_from_state

        state = self.make_state(
            "继续刚才那个工作压力的问题",
            retrieved_counseling_examples=[
                {
                    "chunk_type": "session_sketch",
                    "display_text": "主要困扰：工作压力\n咨询师引导路径：共情承接 -> 澄清压力源",
                    "content": "片段类型：整段咨询地图\n这是更长的 retrieval text，不应该完整展示",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "counseling",
                    "score": 0.99,
                    "rerank_score": 0.9123,
                    "rerank_reasons": ["model_rerank"],
                },
                {
                    "chunk_type": "process_segment",
                    "display_text": "阶段：exploration\n咨询师动作线索：reflection",
                    "content": "片段类型：咨询过程片段\n长对话原文不应该完整展示",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "counseling",
                    "score": 0.95,
                    "rerank_score": None,
                    "rerank_reasons": ["reranker_disabled"],
                },
                {
                    "chunk_type": "turn_pair",
                    "display_text": "用户：我很累\n咨询回应：先慢一点。",
                    "content": "用户：我很累\n咨询回应：先慢一点。",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.9,
                },
            ],
        )

        text = examples_text_from_state(state)

        self.assertIn("--- Session map reference ---", text)
        self.assertIn("--- Process reference ---", text)
        self.assertIn("--- Turn style reference ---", text)
        self.assertIn("Rerank: 0.9123 (model_rerank)", text)
        self.assertIn("Use hint: stronger relevance signal", text)
        self.assertIn("Rerank: fallback (reranker_disabled)", text)
        self.assertIn("Use hint: weak style reference", text)
        self.assertIn("主要困扰：工作压力", text)
        self.assertNotIn("这是更长的 retrieval text，不应该完整展示", text)
        self.assertNotIn("长对话原文不应该完整展示", text)

    def test_examples_text_treats_invalid_rerank_metadata_as_weak_fallback(self) -> None:
        from app.graphs.nodes.response_nodes import examples_text_from_state

        state = self.make_state(
            "继续聊压力",
            retrieved_counseling_examples=[
                {
                    "chunk_type": "turn_pair",
                    "display_text": "用户：我很累\n咨询回应：先慢一点。",
                    "content": "用户：我很累\n咨询回应：先慢一点。",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.9,
                    "rerank_score": "n/a",
                    "rerank_reasons": "model_rerank",
                }
            ],
        )

        text = examples_text_from_state(state)

        self.assertIn("Rerank: fallback (model_rerank)", text)
        self.assertIn("Use hint: weak style reference", text)
        self.assertNotIn("Rerank: 0.", text)
        self.assertNotIn("Use hint: stronger relevance signal", text)

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
