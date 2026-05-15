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
