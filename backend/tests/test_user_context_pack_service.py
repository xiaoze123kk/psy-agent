from __future__ import annotations

import unittest

from app.services.user_context_pack_service import build_user_context_pack


class UserContextPackServiceTests(unittest.TestCase):
    def test_build_user_context_pack_prioritizes_goal_corrections_and_memory_hints(self) -> None:
        pack = build_user_context_pack(
            current_text="还是主管那件事",
            risk_level="L0",
            session_digest={
                "summary_200chars": "用户持续讨论职场压力和任务边界。",
                "key_themes": ["职场压力", "任务边界"],
                "unresolved_threads": ["如何和主管开口"],
            },
            user_profile_digest={
                "usage_goals": ["先安抚再建议"],
                "profile_hints": ["用户在重要沟通前会先写提纲"],
                "preference_hints": ["用户希望回复短一点"],
                "correction_hints": ["不要直接给模板"],
            },
            goal_state={
                "current_goal": "用户澄清当前想谈：主管那件事",
                "clarification_answer": "主管那件事",
                "open_threads": ["任务边界"],
            },
            retrieved_memories=[
                {
                    "memory_type": "correction",
                    "content": "用户纠正：不要直接给模板，先帮他梳理边界。",
                    "summary": "不要直接给模板",
                },
                {
                    "memory_type": "goal",
                    "content": "用户目标：理清楚和主管沟通任务边界。",
                    "summary": "理清楚任务边界",
                },
            ],
        )

        self.assertEqual(pack["schema_version"], 1)
        self.assertIn("主管那件事", pack["active_goal"])
        self.assertIn("职场压力", pack["conversation_focus"])
        self.assertIn("不要直接给模板", pack["style_corrections"])
        self.assertIn("用户在重要沟通前会先写提纲", pack["profile_hints"])
        self.assertIn("如何和主管开口", pack["open_threads"])
        self.assertTrue(any("理清楚任务边界" in item for item in pack["retrieved_memory_hints"]))
        self.assertEqual(pack["priority_notes"][0], "优先围绕当前目标和澄清答案回应")

    def test_build_user_context_pack_limits_list_lengths(self) -> None:
        pack = build_user_context_pack(
            current_text="继续",
            risk_level="L0",
            session_digest={"unresolved_threads": [f"线索 {index}" for index in range(8)]},
            user_profile_digest={"profile_hints": [f"画像 {index}" for index in range(8)]},
            goal_state={"goal_hints": [f"目标 {index}" for index in range(8)]},
            retrieved_memories=[
                {"memory_type": "session_summary", "content": f"记忆 {index}", "summary": f"记忆 {index}"}
                for index in range(8)
            ],
        )

        self.assertLessEqual(len(pack["profile_hints"]), 5)
        self.assertLessEqual(len(pack["open_threads"]), 5)
        self.assertLessEqual(len(pack["retrieved_memory_hints"]), 5)

    def test_build_user_context_pack_filters_ordinary_context_for_high_risk(self) -> None:
        pack = build_user_context_pack(
            current_text="我现在不安全",
            risk_level="L2",
            session_digest={"summary_200chars": "普通对话摘要", "unresolved_threads": ["普通未展开线索"]},
            user_profile_digest={
                "profile_hints": ["普通画像"],
                "correction_hints": ["不要直接给模板"],
            },
            goal_state={"current_goal": "普通目标"},
            retrieved_memories=[
                {"memory_type": "preference", "content": "普通偏好", "visibility": "user_visible"},
                {"memory_type": "safety_summary", "content": "概括性安全连续性", "visibility": "internal_safety"},
            ],
        )

        self.assertEqual(pack["active_goal"], "")
        self.assertEqual(pack["profile_hints"], [])
        self.assertEqual(pack["style_corrections"], [])
        self.assertEqual(pack["open_threads"], [])
        self.assertEqual(pack["conversation_focus"], "高风险场景：只保留安全连续性和当前安全处理。")
        self.assertEqual(pack["retrieved_memory_hints"], ["安全摘要：概括性安全连续性"])


if __name__ == "__main__":
    unittest.main()
