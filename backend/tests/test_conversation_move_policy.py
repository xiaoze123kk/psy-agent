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

    def test_current_anger_is_treated_as_current_feeling_not_ordinary_chat(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我感到很生气",
                "normalized_text": "我感到很生气",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["topic_anchor"], "none")
        self.assertNotEqual(policy["conversation_move"], "ordinary_chat")
        self.assertIn("当下内容", policy["handling"])

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

    def test_repeated_two_beat_question_structure_requests_single_paragraph(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "在轮下，记得吗",
                "normalized_text": "在轮下，记得吗",
                "risk_level": "L0",
                "recent_messages": [
                    {
                        "role": "assistant",
                        "content": "听起来《在轮下》这个比喻很贴近你。\n\n你是不是想说那种停不下来的压力？",
                    },
                    {"role": "user", "content": "嗯，就是不能慢。"},
                    {
                        "role": "assistant",
                        "content": "那种不能慢的感觉像是一直被推着往前。\n\n你觉得最重的是学校，还是整个社会？",
                    },
                ],
            }
        )

        self.assertEqual(policy["structure_mode"], "single_paragraph")
        self.assertEqual(policy["avoid_structure"], "two_beat_question")
        self.assertTrue(policy["avoid_reused_structure"])
        self.assertIn("两段式整理+追问", policy["structure_style"])

    def test_person_anchor_is_detected_from_sentence_shape_without_name_list(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "你觉得林秋白是个什么样的人",
                "normalized_text": "你觉得林秋白是个什么样的人",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["conversation_move"], "respond_to_anchor")
        self.assertEqual(policy["topic_anchor"], "person")
        self.assertEqual(policy["anchor_value"], "林秋白")
        self.assertEqual(policy["button_style"], "topic_continue")
        self.assertIn("真实话题", policy["handling"])

    def test_unquoted_recent_book_title_continues_from_context_without_title_list(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "在轮下，记得吗",
                "normalized_text": "在轮下，记得吗",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "assistant", "content": "你刚才提到《在轮下》，那个画面很重。"},
                    {"role": "user", "content": "嗯，就是不能慢。"},
                ],
            }
        )

        self.assertEqual(policy["topic_anchor"], "literary")
        self.assertEqual(policy["anchor_value"], "在轮下")
        self.assertEqual(policy["button_style"], "topic_continue")

    def test_recent_literary_anchor_is_suppressed_when_user_moves_to_new_feeling(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我感到很生气",
                "normalized_text": "我感到很生气",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "在轮下，记得吗"},
                    {"role": "assistant", "content": "记得，《在轮下》那个锚点很准。"},
                    {"role": "user", "content": "情绪最近不是很好其实"},
                    {
                        "role": "assistant",
                        "content": "你刚才提到《在轮下》，又说到情绪不好。",
                    },
                ],
            }
        )

        self.assertEqual(policy["topic_anchor"], "none")
        self.assertEqual(policy["anchor_value"], "")
        self.assertEqual(policy["button_style"], "user_voice")
        self.assertEqual(policy["suppressed_recent_anchors"], ["在轮下"])
        self.assertIn("不要主动带回", policy["stale_anchor_handling"])

    def test_multilane_input_marks_primary_secondary_and_blocking_boundary(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。",
                "normalized_text": "我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["primary_lane"], "self_reference")
        lanes = policy["intent_lanes"]
        self.assertTrue(
            any(
                lane["kind"] == "cultural_anchor"
                and lane["anchor_value"] == "德米安"
                and lane["priority"] == "secondary"
                and lane["handling"] == "do_not_expand_work_detail"
                for lane in lanes
            )
        )
        self.assertTrue(
            any(
                lane["kind"] == "self_reference"
                and lane["priority"] == "primary"
                and "找自己" in lane["user_clues"]
                for lane in lanes
            )
        )
        self.assertTrue(
            any(
                lane["kind"] == "boundary"
                and lane["priority"] == "blocking_style_constraint"
                and lane["handling"] == "lower_analysis_depth"
                for lane in lanes
            )
        )

    def test_voice_contract_quiet_presence_stops_without_question(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "嗯，就停在这儿吧。",
                "normalized_text": "嗯，就停在这儿吧。",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        contract = policy["ningyu_voice_contract"]

        self.assertEqual(contract["voice_mode"], "quiet_presence")
        self.assertEqual(contract["question_budget"], 0)
        self.assertEqual(contract["sentence_budget"], "1-2")
        self.assertEqual(contract["closing_preference"], "pause")

    def test_recent_question_correction_decays_into_short_term_adaptation(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我只是觉得今天有点空。",
                "normalized_text": "我只是觉得今天有点空。",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "别一直问我问题。"},
                    {
                        "role": "assistant",
                        "content": "行，我先不追问。",
                        "metadata": {
                            "conversation_move_policy": {
                                "adaptation_state": {
                                    "avoid_questions_turns": 2,
                                    "avoid_analysis_turns": 0,
                                    "avoid_safety_check_turns": 0,
                                    "prefer_direct_anchor_response_turns": 0,
                                    "last_correction_type": "too_many_questions",
                                }
                            }
                        },
                    },
                ],
            }
        )

        self.assertEqual(policy["adaptation_state"]["avoid_questions_turns"], 1)
        self.assertEqual(policy["ningyu_voice_contract"]["question_budget"], 0)
        self.assertIn("减少问句", policy["adaptation_state_delta"]["notes"])

    def test_negative_explicit_feedback_applies_short_term_adaptation(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "just stay with this a bit",
                "normalized_text": "just stay with this a bit",
                "risk_level": "L0",
                "recent_messages": [
                    {
                        "role": "assistant",
                        "content": "previous assistant reply",
                        "metadata": {
                            "conversation_quality_trace": {
                                "user_signal": {
                                    "explicit_feedback": "too_analytic",
                                    "next_turn_signal": "unknown",
                                }
                            }
                        },
                    }
                ],
            }
        )

        self.assertEqual(policy["adaptation_state"]["avoid_analysis_turns"], 3)
        self.assertEqual(policy["adaptation_state"]["prefer_direct_anchor_response_turns"], 2)
        self.assertEqual(policy["adaptation_state"]["last_correction_type"], "feedback_too_analytic")
        self.assertEqual(policy["ningyu_voice_contract"]["analysis_depth"], "none")
        self.assertEqual(policy["adaptation_state_delta"]["source"], "explicit_feedback")

    def test_too_many_questions_feedback_reduces_next_turn_question_budget(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "I felt empty today",
                "normalized_text": "I felt empty today",
                "risk_level": "L0",
                "recent_messages": [
                    {
                        "role": "assistant",
                        "content": "previous assistant reply?",
                        "metadata": {
                            "trace_summary": {
                                "conversation_quality": {
                                    "user_signal": {
                                        "explicit_feedback": "too_many_questions",
                                        "next_turn_signal": "unknown",
                                    }
                                }
                            }
                        },
                    }
                ],
            }
        )

        self.assertEqual(policy["adaptation_state"]["avoid_questions_turns"], 3)
        self.assertEqual(policy["ningyu_voice_contract"]["question_budget"], 0)
        self.assertEqual(policy["adaptation_state"]["last_correction_type"], "feedback_too_many_questions")

    def test_correction_fallback_buttons_include_nonlisted_person_anchor(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "别问安全了，我想聊阿伦特",
                "normalized_text": "别问安全了，我想聊阿伦特",
                "risk_level": "L0",
                "recent_messages": [
                    {"role": "user", "content": "有点想死", "risk_level": "L2"},
                    {"role": "assistant", "content": "你现在安全吗？", "risk_level": "L2"},
                ],
            }
        )

        actions = default_actions_for_conversation_move_policy(policy)

        self.assertEqual(policy["correction_state"]["correction_type"], "too_safety_focused")
        self.assertEqual(policy["topic_anchor"], "person")
        self.assertEqual(policy["anchor_value"], "阿伦特")
        self.assertTrue(any("阿伦特" in action for action in actions))

    def test_cultural_anchor_evidence_tracks_user_clues_and_forbidden_claims(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
                "normalized_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        evidence = policy["anchor_evidence"]

        self.assertEqual(policy["topic_anchor"], "literary")
        self.assertEqual(policy["anchor_value"], "德米安")
        self.assertEqual(evidence["anchor_type"], "literary")
        self.assertEqual(evidence["anchor_value"], "德米安")
        self.assertEqual(evidence["confidence"], "explicit")
        self.assertIn("user_clues", evidence)
        self.assertTrue(
            any(
                clue["text"] == "没读过" and clue["kind"] == "knowledge_boundary"
                for clue in evidence["user_clues"]
            )
        )
        self.assertTrue(
            any(
                clue["text"] == "自我寻找" and clue["kind"] == "theme"
                for clue in evidence["user_clues"]
            )
        )
        self.assertEqual(evidence["response_mode"], "echo_user_clue")
        self.assertIn("plot_detail", evidence["forbidden_claims"])
        self.assertIn("author_intent", evidence["forbidden_claims"])
        self.assertEqual(policy["cultural_response_mode"], "echo_user_clue")

    def test_cultural_anchor_evidence_uses_no_knowledge_claim_for_uncertain_reference(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我记不清原句了，大概是说人一直被什么东西推着走",
                "normalized_text": "我记不清原句了，大概是说人一直被什么东西推着走",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        evidence = policy["anchor_evidence"]

        self.assertEqual(evidence["anchor_type"], "quote")
        self.assertEqual(evidence["response_mode"], "no_knowledge_claim")
        self.assertTrue(any(clue["text"] == "记不清原句" for clue in evidence["user_clues"]))
        self.assertTrue(any(clue["text"] == "被什么东西推着走" for clue in evidence["user_clues"]))
        self.assertEqual(policy["cultural_response_mode"], "no_knowledge_claim")

    def test_person_anchor_without_clues_asks_user_association(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "你觉得林秋白是个什么样的人",
                "normalized_text": "你觉得林秋白是个什么样的人",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        evidence = policy["anchor_evidence"]

        self.assertEqual(policy["topic_anchor"], "person")
        self.assertEqual(evidence["anchor_value"], "林秋白")
        self.assertEqual(evidence["response_mode"], "ask_user_association")
        self.assertIn("user_clues", evidence)

    def test_anchor_evidence_omits_surface_text_to_avoid_metadata_duplication(self) -> None:
        long_text = "我没读过《德米安》，只是听别人说它和自我寻找有关。" + "这部分私人背景很长" * 20
        policy = build_conversation_move_policy(
            {
                "user_text": long_text,
                "normalized_text": long_text,
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        evidence = policy["anchor_evidence"]

        self.assertNotIn("surface_text", evidence)

    def test_common_bare_cultural_anchors_still_route_as_cultural_topics(self) -> None:
        cases = [
            ("荣格", "philosophical", "荣格"),
            ("德米安", "literary", "德米安"),
            ("黑塞", "person", "黑塞"),
        ]

        for text, anchor_type, anchor_value in cases:
            with self.subTest(text=text):
                policy = build_conversation_move_policy(
                    {
                        "user_text": text,
                        "normalized_text": text,
                        "risk_level": "L0",
                        "recent_messages": [],
                    }
                )

                self.assertEqual(policy["conversation_move"], "respond_to_anchor")
                self.assertEqual(policy["topic_anchor"], anchor_type)
                self.assertEqual(policy["anchor_value"], anchor_value)
                self.assertEqual(policy["anchor_evidence"]["response_mode"], "light_context_only")

    def test_uncertain_quote_without_metaphor_still_routes_as_cultural_anchor(self) -> None:
        policy = build_conversation_move_policy(
            {
                "user_text": "我记不清原句了，大概是关于孤独",
                "normalized_text": "我记不清原句了，大概是关于孤独",
                "risk_level": "L0",
                "recent_messages": [],
            }
        )

        self.assertEqual(policy["conversation_move"], "respond_to_anchor")
        self.assertEqual(policy["topic_anchor"], "quote")
        self.assertEqual(policy["anchor_evidence"]["response_mode"], "no_knowledge_claim")


if __name__ == "__main__":
    unittest.main()
