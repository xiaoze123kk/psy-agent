from __future__ import annotations

import unittest

from app.services.conversation_quality_service import build_conversation_quality_trace, infer_next_turn_signal


class ConversationQualityTraceTests(unittest.TestCase):
    def test_quality_trace_contains_required_sections_without_raw_text(self) -> None:
        user_text = "我不是想聊《德米安》本身，就是觉得找自己有点像我。"
        assistant_text = "找自己这几个字放在你这里，好像不是书的问题，是你在辨认哪部分更像自己。"

        trace = build_conversation_quality_trace(
            assistant_text=assistant_text,
            suggested_actions=["先停在找自己"],
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "literary",
                "anchor_value": "德米安",
                "ningyu_voice_contract": {"voice_mode": "anchored_companion"},
            },
            risk_level="L0",
            validator_severity="warning",
            validator_reasons=[],
            experience_validator_reasons=["missed_primary_lane"],
            regeneration_attempted=False,
        )

        self.assertIn("turn_shape", trace)
        self.assertIn("policy_snapshot", trace)
        self.assertIn("validator_snapshot", trace)
        self.assertIn("user_signal", trace)
        self.assertEqual(trace["policy_snapshot"]["conversation_move"], "respond_to_anchor")
        self.assertEqual(trace["policy_snapshot"]["topic_anchor_type"], "literary")
        self.assertEqual(trace["policy_snapshot"]["voice_mode"], "anchored_companion")
        self.assertEqual(trace["validator_snapshot"]["severity"], "warning")
        self.assertEqual(trace["user_signal"]["explicit_feedback"], "none")
        self.assertEqual(trace["turn_shape"]["question_count"], 0)
        self.assertNotIn(user_text, str(trace))
        self.assertNotIn(assistant_text, str(trace))

    def test_quality_trace_buckets_reply_shape(self) -> None:
        trace = build_conversation_quality_trace(
            assistant_text="先停在这里，不用急着往下说。",
            suggested_actions=[],
            conversation_move_policy={"conversation_move": "continue_thread"},
            risk_level="L0",
            validator_severity="passed",
            validator_reasons=[],
            experience_validator_reasons=[],
            regeneration_attempted=True,
        )

        self.assertEqual(trace["turn_shape"]["assistant_length_bucket"], "short")
        self.assertEqual(trace["turn_shape"]["closing_pattern"], "pause")
        self.assertTrue(trace["validator_snapshot"]["regeneration_attempted"])

    def test_infer_next_turn_signal_from_following_user_message(self) -> None:
        self.assertEqual(infer_next_turn_signal("\u4e0d\u662f\u8fd9\u4e2a\u610f\u601d"), "corrected")
        self.assertEqual(infer_next_turn_signal("\u5c31\u5148\u505c\u5728\u8fd9\u91cc\u5427"), "stopped")
        self.assertEqual(infer_next_turn_signal("\u7ee7\u7eed\u8bf4"), "continued")


if __name__ == "__main__":
    unittest.main()
