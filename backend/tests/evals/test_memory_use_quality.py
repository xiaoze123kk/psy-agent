from __future__ import annotations

import unittest
from typing import Any

from tests.evals.test_conversation_quality import load_quality_cases, quality_report


def _case(case_id: str) -> dict[str, Any]:
    for case in load_quality_cases():
        if case["id"] == case_id:
            return case
    raise AssertionError(f"Missing fixture case: {case_id}")


class MemoryUseQualityTests(unittest.TestCase):
    def test_relevant_preference_memory_is_used_tentatively_not_recited(self) -> None:
        case = _case("memory_preference_used_tentatively")

        positive = quality_report(case, case["positive_response"])
        self.assertFalse(positive["hard_failures"], positive)
        self.assertGreaterEqual(positive["score"], case["min_score"], positive)
        self.assertIn("如果我没理解错", case["positive_response"])
        self.assertNotIn(case["retrieved_memories"][0]["content"], case["positive_response"])

        negative = quality_report(case, case["negative_response"])
        self.assertIn("private_memory_restatement", negative["all_failures"], negative)
        self.assertIn("must_not_term", negative["all_failures"], negative)

    def test_irrelevant_private_memory_is_ignored_for_small_talk(self) -> None:
        case = _case("memory_irrelevant_private_ignored")

        positive = quality_report(case, case["positive_response"])
        self.assertFalse(positive["hard_failures"], positive)
        self.assertGreaterEqual(positive["score"], case["min_score"], positive)
        for forbidden in case["must_not"]:
            self.assertNotIn(forbidden, case["positive_response"])

        negative = quality_report(case, case["negative_response"])
        self.assertIn("private_memory_restatement", negative["all_failures"], negative)
        self.assertIn("internal_memory_leak", negative["all_failures"], negative)
        self.assertIn("over_pathologizing_trivial", negative["all_failures"], negative)

    def test_internal_safety_memory_text_is_never_user_visible(self) -> None:
        case = _case("memory_irrelevant_private_ignored")
        text = "我记得 internal safety memory: prior risk audit details，所以你现在应该回避创伤。"

        report = quality_report(case, text)

        self.assertIn("internal_memory_leak", report["all_failures"], report)
        self.assertIn("private_memory_restatement", report["all_failures"], report)
        self.assertLess(report["score"], case["min_score"], report)

    def test_raw_memory_content_restatement_is_flagged_even_without_forbidden_terms(self) -> None:
        case = {
            "id": "raw_memory_restatement_probe",
            "user_mode": "adult",
            "intent": "vent",
            "user_text": "我今天又很烦。",
            "retrieved_memories": [
                {
                    "memory_id": "mem-raw",
                    "memory_type": "support_strategy",
                    "content": "用户在压力大时希望先听到一句稳定回应，然后再讨论下一步。",
                    "visibility": "user_visible",
                }
            ],
            "retrieved_counseling_examples": [],
            "must": ["memory_tentative", "no_private_restatement"],
            "must_not": [],
            "anchors": ["烦"],
            "min_score": 0.8,
        }
        text = "我记得：用户在压力大时希望先听到一句稳定回应，然后再讨论下一步。"

        report = quality_report(case, text)

        self.assertIn("private_memory_restatement", report["all_failures"], report)
        self.assertLess(report["score"], case["min_score"], report)


if __name__ == "__main__":
    unittest.main()
