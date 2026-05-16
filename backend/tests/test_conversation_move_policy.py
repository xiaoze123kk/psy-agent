from __future__ import annotations

import unittest

from app.services.conversation_move_policy import build_conversation_move_policy


class ConversationMovePolicyTests(unittest.TestCase):
    def test_literary_anchor_continues_after_recent_assistant_question(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "在轮下，记得吗",
                "normalized_text": "在轮下，记得吗",
                "risk_level": "L0",
                "recent_messages": [
                    {
                        "role": "assistant",
                        "content": "你提到《在轮下》，是因为今天被现实推着跑的感觉，让你想起它了吗？",
                    },
                    {"role": "user", "content": "嗯，就是那种一直奔跑，不然会被碾死。"},
                    {
                        "role": "assistant",
                        "content": "那种被轮子追着的感觉，是更像窒息，还是更像没有退路？",
                    },
                ],
            }
        )

        self.assertIn(policy["conversation_move"], {"respond_to_anchor", "continue_thread"})
        self.assertIn(policy["topic_anchor"], {"literary", "metaphor"})
        self.assertEqual(policy["button_style"], "topic_continue")
        self.assertIn(policy["psychologizing_risk"], {"low", "medium"})
        self.assertIn("不心理化", policy["handling"])

    def test_user_correction_about_over_psychologizing_sets_followup_policy(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "不是这个意思，你又在心理分析了",
                "normalized_text": "不是这个意思，你又在心理分析了",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "我今天只是看到一朵花。"},
                    {"role": "assistant", "content": "也许花让你想到了某种被压抑的创伤。"},
                ],
            }
        )

        self.assertEqual(policy["conversation_move"], "correction_followup")
        self.assertEqual(policy["correction_state"]["correction_type"], "too_psychological")
        self.assertEqual(policy["button_style"], "user_voice")

    def test_ordinary_daily_detail_marks_high_over_psychologizing_risk(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "今天看到一朵花",
                "normalized_text": "今天看到一朵花",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["conversation_move"], "ordinary_chat")
        self.assertEqual(policy["topic_anchor"], "daily_detail")
        self.assertEqual(policy["psychologizing_risk"], "high")
        self.assertEqual(policy["button_style"], "user_voice")

    def test_post_l2_return_to_jung_topic_does_not_use_safety_micro_reply(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "你觉得荣格是个什么样的人",
                "normalized_text": "你觉得荣格是个什么样的人",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "有点想死", "risk_level": "L2"},
                    {"role": "assistant", "content": "我在，我们先把这一刻放慢一点。", "risk_level": "L2"},
                ],
            }
        )

        self.assertIn(policy["conversation_move"], {"post_risk_return", "respond_to_anchor"})
        self.assertEqual(policy["button_style"], "topic_continue")
        self.assertNotEqual(policy.get("style_variation"), "safety_micro_reply")


if __name__ == "__main__":
    unittest.main()
