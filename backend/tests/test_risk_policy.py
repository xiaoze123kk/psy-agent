from __future__ import annotations

import unittest

from app.services.risk_policy import (
    build_risk_response_policy,
    default_actions_for_policy,
    derive_immediacy,
    derive_risk_domain,
    derive_risk_phase,
    tool_gate_mode_for_state,
)


class RiskPolicyTests(unittest.TestCase):
    def test_self_harm_near_term_policy_uses_brief_first_contact(self) -> None:
        state = {
            "risk_level": "L3",
            "control_category": "self_harm_risk",
            "semantic_risk": {"means": True, "timeframe": "near_term"},
            "normalized_text": "我现在不想活了，那个东西就在手边",
            "recent_messages": [],
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_domain"], "self_harm")
        self.assertEqual(policy["immediacy"], "near_term")
        self.assertEqual(policy["risk_phase"], "first_contact")
        self.assertEqual(policy["length_profile"], "brief_first_contact")
        self.assertEqual(policy["char_budget"]["target"], 220)
        self.assertIn("micro_safety_step", policy["allowed_moves"])
        self.assertIn("professional_referral_first_turn", policy["forbidden_moves"])

    def test_normal_support_after_question_streak_uses_no_question_budget(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L0",
                "control_category": "normal_support",
                "normalized_text": "在轮下，记得吗",
                "recent_messages": [
                    {"role": "assistant", "content": "你是想聊这本书吗？"},
                    {"role": "user", "content": "记得"},
                ],
            }
        )

        self.assertEqual(policy["ending_style"], "reflective_pause")
        self.assertEqual(policy["question_budget"], 0)
        self.assertEqual(policy["avoid_question_reason"], "previous_turn_ended_with_question")
        self.assertEqual(policy["question_ending_streak"], 1)
        self.assertFalse(policy["last_turn_had_safety_question"])
        self.assertTrue(policy["user_answered_previous_question"])
        self.assertEqual(policy["max_questions"], 1)

    def test_normal_support_defaults_to_no_question_budget(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L0",
                "control_category": "normal_support",
                "normalized_text": "今天只是想随便聊聊在轮下",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["ending_style"], "natural_close")
        self.assertEqual(policy["question_budget"], 0)
        self.assertEqual(policy["avoid_question_reason"], "no_clarification_needed")

    def test_l1_distress_after_question_streak_uses_no_question_budget(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L1",
                "control_category": "normal_support",
                "semantic_risk": {"risk_domain": "general_distress"},
                "normalized_text": "就是那种一直被推着跑的感觉",
                "recent_messages": [
                    {"role": "assistant", "content": "你是觉得自己也被什么东西一直往下压吗？"},
                    {"role": "user", "content": "就是那种一直被推着跑的感觉"},
                ],
            }
        )

        self.assertEqual(policy["risk_domain"], "general_distress")
        self.assertEqual(policy["ending_style"], "reflective_pause")
        self.assertEqual(policy["question_budget"], 0)
        self.assertEqual(policy["avoid_question_reason"], "previous_turn_ended_with_question")

    def test_l3_first_contact_allows_immediate_safety_question(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L3",
                "control_category": "self_harm_risk",
                "semantic_risk": {"means": True, "timeframe": "near_term"},
                "normalized_text": "我现在不想活了，那个东西就在手边",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["ending_style"], "micro_step")
        self.assertEqual(policy["question_budget"], 1)
        self.assertEqual(policy["allow_question_reason"], "immediate_safety_check")
        self.assertEqual(policy["question_ending_streak"], 0)
        self.assertFalse(policy["last_turn_had_safety_question"])
        self.assertFalse(policy["user_answered_previous_question"])
        self.assertEqual(policy["max_questions"], 1)

    def test_l3_first_contact_does_not_treat_safety_words_as_answer_without_previous_question(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L3",
                "control_category": "self_harm_risk",
                "semantic_risk": {"means": True, "timeframe": "near_term"},
                "normalized_text": "我还在楼顶，那个东西还在手边，但我没有计划",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["ending_style"], "micro_step")
        self.assertEqual(policy["question_budget"], 1)
        self.assertEqual(policy["allow_question_reason"], "immediate_safety_check")
        self.assertIsNone(policy["avoid_question_reason"])

    def test_deescalating_safety_answer_stops_repeated_safety_question(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L2",
                "control_category": "self_harm_risk",
                "semantic_risk": {"protective_factor": True},
                "normalized_text": "我现在安全，没有计划",
                "recent_messages": [
                    {"role": "assistant", "content": "你现在安全吗？"},
                    {"role": "user", "content": "我现在安全，没有计划"},
                ],
            }
        )

        self.assertEqual(policy["ending_style"], "micro_step")
        self.assertEqual(policy["question_budget"], 0)
        self.assertEqual(policy["avoid_question_reason"], "safety_answer_already_given")
        self.assertEqual(policy["question_ending_streak"], 1)
        self.assertTrue(policy["last_turn_had_safety_question"])
        self.assertTrue(policy["user_answered_previous_question"])
        self.assertEqual(policy["max_questions"], 1)

    def test_clarification_needed_allows_factual_clarification_question(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L1",
                "control_category": "normal_support",
                "normalized_text": "不是那本书，是另一篇",
                "clarification_needed": True,
                "recent_messages": [
                    {"role": "assistant", "content": "我先确认一下你说的是哪本。"},
                    {"role": "user", "content": "不是那本书，是另一篇"},
                ],
            }
        )

        self.assertEqual(policy["ending_style"], "question")
        self.assertEqual(policy["question_budget"], 1)
        self.assertEqual(policy["allow_question_reason"], "factual_clarification")
        self.assertEqual(policy["question_ending_streak"], 0)
        self.assertFalse(policy["last_turn_had_safety_question"])
        self.assertFalse(policy["user_answered_previous_question"])
        self.assertEqual(policy["max_questions"], 1)

    def test_deescalating_policy_allows_warm_medium_length(self) -> None:
        state = {
            "risk_level": "L2",
            "control_category": "self_harm_risk",
            "semantic_risk": {"protective_factor": True},
            "normalized_text": "我还在，暂时不会动",
            "recent_messages": [
                {"role": "user", "content": "我刚才真的很想伤害自己"},
                {"role": "assistant", "content": "我们先只过这一分钟。"},
            ],
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_phase"], "deescalating")
        self.assertEqual(policy["length_profile"], "warm_medium")
        self.assertGreater(policy["char_budget"]["target"], 300)

    def test_medical_request_maps_to_firm_brief(self) -> None:
        state = {
            "risk_level": "L0",
            "control_category": "diagnosis_or_medical_request",
            "normalized_text": "我能不能停药，剂量怎么调",
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_domain"], "medical_request")
        self.assertEqual(policy["length_profile"], "firm_brief")
        self.assertIn("medication_or_dosage_advice", policy["forbidden_moves"])

    def test_tool_gate_mode_uses_safety_context_for_l2_l3(self) -> None:
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L2"}), "safety_context")
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L3"}), "safety_context")
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L1"}), "normal_context")
        self.assertEqual(
            tool_gate_mode_for_state({"risk_level": "L1", "control_category": "prompt_attack"}),
            "blocked_context",
        )

    def test_semantic_risk_domain_overrides_control_category(self) -> None:
        self.assertEqual(
            derive_risk_domain(
                {
                    "risk_level": "L2",
                    "control_category": "self_harm_risk",
                    "semantic_risk": {"risk_domain": "non_suicidal_self_injury"},
                }
            ),
            "non_suicidal_self_injury",
        )
        self.assertEqual(
            derive_risk_domain(
                {
                    "risk_level": "L3",
                    "control_category": "third_party_self_harm_risk",
                    "semantic_risk": {"risk_domain": "none"},
                }
            ),
            "self_harm",
        )

    def test_non_suicidal_self_injury_policy_avoids_suicide_labeling_and_referral_first(self) -> None:
        policy = build_risk_response_policy(
            {
                "risk_level": "L2",
                "control_category": "self_harm_risk",
                "semantic_risk": {
                    "risk_domain": "non_suicidal_self_injury",
                    "risk_expression_type": "non_suicidal_self_injury_urge",
                },
                "normalized_text": "我控制不住想弄疼自己",
            }
        )

        self.assertEqual(policy["risk_domain"], "non_suicidal_self_injury")
        self.assertIn("reduce_access_to_injury", policy["allowed_moves"])
        self.assertIn("suicide_labeling", policy["forbidden_moves"])
        self.assertIn("professional_referral_first_turn", policy["forbidden_moves"])

    def test_actions_follow_policy_without_professional_referral_first_turn(self) -> None:
        policy = {
            "risk_domain": "self_harm",
            "immediacy": "near_term",
            "risk_phase": "first_contact",
            "length_profile": "brief_first_contact",
        }

        actions = default_actions_for_policy(policy)

        self.assertEqual(actions, ["我还在", "我退开一点了", "我身边有人", "请继续跟我说"])
        self.assertFalse(any("咨询" in action or "医院" in action for action in actions))

    def test_direct_helpers_are_stable(self) -> None:
        self.assertEqual(derive_risk_domain({"control_category": "harm_to_other_risk"}), "harm_other")
        self.assertEqual(derive_immediacy({"semantic_risk": {"means": True}}), "near_term")
        self.assertEqual(derive_risk_phase({"risk_level": "L0", "recent_messages": []}), "first_contact")


if __name__ == "__main__":
    unittest.main()
