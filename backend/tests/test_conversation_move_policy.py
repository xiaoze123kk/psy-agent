from __future__ import annotations

import unittest

from app.services.conversation_move_policy import (
    build_conversation_move_policy,
    default_actions_for_conversation_move_policy,
)


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

    def test_safety_loop_correction_is_prioritized_over_generic_question_correction(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "别一直问我安不安全了，我想聊点别的",
                "normalized_text": "别一直问我安不安全了，我想聊点别的",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "有点想死", "risk_level": "L2"},
                    {"role": "assistant", "content": "你现在安全吗？身边有人吗？", "risk_level": "L2"},
                ],
            }
        )

        self.assertEqual(policy["conversation_move"], "correction_followup")
        self.assertEqual(policy["correction_state"]["correction_type"], "too_safety_focused")
        self.assertEqual(policy["button_style"], "user_voice")
        self.assertIn("安全", policy["handling"])

    def test_safety_loop_correction_overrides_psychological_correction_phrase(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "别一直问我安不安全了，不要心理分析，我想聊点别的",
                "normalized_text": "别一直问我安不安全了，不要心理分析，我想聊点别的",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "有点想死", "risk_level": "L2"},
                    {"role": "assistant", "content": "你现在安全吗？", "risk_level": "L2"},
                ],
            }
        )

        self.assertEqual(policy["correction_state"]["correction_type"], "too_safety_focused")

    def test_topic_continue_fallback_buttons_include_anchor_value(self) -> None:
        actions = default_actions_for_conversation_move_policy(
            {
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "philosophical",
                "anchor_value": "荣格",
                "button_style": "topic_continue",
            }
        )

        self.assertTrue(any("荣格" in action for action in actions))
        self.assertNotIn("继续陪我", actions)
        self.assertFalse(any("继续说" in action for action in actions))

    def test_daily_detail_fallback_buttons_include_daily_anchor(self) -> None:
        actions = default_actions_for_conversation_move_policy(
            {
                "conversation_move": "ordinary_chat",
                "topic_anchor": "daily_detail",
                "anchor_value": "花",
                "button_style": "user_voice",
            }
        )

        self.assertTrue(any("花" in action for action in actions))
        self.assertFalse(any("分析" in action or "建议" in action for action in actions))

    def test_correction_fallback_buttons_include_new_anchor_when_available(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "别问安全了，我想聊荣格",
                "normalized_text": "别问安全了，我想聊荣格",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "有点想死", "risk_level": "L2"},
                    {"role": "assistant", "content": "你现在安全吗？", "risk_level": "L2"},
                ],
            }
        )

        actions = default_actions_for_conversation_move_policy(policy)

        self.assertEqual(policy["correction_state"]["correction_type"], "too_safety_focused")
        self.assertTrue(any("荣格" in action for action in actions))


if __name__ == "__main__":
    unittest.main()
