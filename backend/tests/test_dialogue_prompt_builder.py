from __future__ import annotations

import unittest

from app.graphs.state import AgentState
from app.services.dialogue_prompt_builder import build_dialogue_prompt_parts


class DialoguePromptBuilderTests(unittest.TestCase):
    def make_state(self, **overrides) -> AgentState:
        state: AgentState = {
            "normalized_text": "我还是卡在和主管沟通任务边界这一步",
            "user_text": "我还是卡在和主管沟通任务边界这一步",
            "profile": {"user_mode": "adult"},
            "companion_preferences": {"style": "gentle"},
            "last_summary": "用户最近在聊工作压力。",
            "session_digest": {},
            "route_priority": "P2_support",
            "control_category": "normal_support",
            "risk_level": "L0",
        }
        state.update(overrides)
        return state

    def test_prompt_includes_compact_session_digest_fields(self) -> None:
        state = self.make_state(
            session_digest={
                "schema_version": 1,
                "key_themes": ["职场压力", "任务边界"],
                "emotional_arc": "紧张 -> 疲惫 -> 稍微松动",
                "effective_interventions": ["先共情再轻量梳理"],
                "ineffective_interventions": [],
                "unresolved_threads": ["如何和主管开口"],
                "significant_changes": ["用户已经尝试整理任务清单"],
                "last_updated_turn": 5,
                "summary_200chars": "用户持续讨论职场压力和任务边界，当前最卡在如何与主管开口。",
            }
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("会话全景", parts.user_prompt)
        self.assertIn("用户持续讨论职场压力和任务边界", parts.user_prompt)
        self.assertIn("稳定主题：职场压力、任务边界", parts.user_prompt)
        self.assertIn("未展开线索：如何和主管开口", parts.user_prompt)
        self.assertIn("有效回应：先共情再轻量梳理", parts.user_prompt)
        self.assertNotIn("schema_version", parts.user_prompt)
        self.assertNotIn("last_updated_turn", parts.user_prompt)

    def test_prompt_omits_empty_session_digest_block(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(session_digest={}),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertNotIn("会话全景", parts.user_prompt)

    def test_prompt_includes_temporal_context_without_guessing_time(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                normalized_text="你知道现在几点了吗",
                user_text="你知道现在几点了吗",
                temporal_context={
                    "local_date": "2026-05-17",
                    "local_time": "12:30",
                    "timezone": "Asia/Wuhan",
                    "weekday": "星期日",
                    "day_period": "中午",
                    "companion_hint": "中午可以轻轻提醒吃点东西或歇一下。",
                },
            ),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("当前时间上下文", parts.user_prompt)
        self.assertIn("2026-05-17 12:30", parts.user_prompt)
        self.assertIn("Asia/Wuhan", parts.user_prompt)
        self.assertIn("星期日", parts.user_prompt)
        self.assertIn("中午", parts.user_prompt)
        self.assertIn("不要猜时间", parts.user_prompt)
        self.assertIn("不要反问用户在哪", parts.user_prompt)

    def test_prompt_includes_user_profile_digest_block(self) -> None:
        state = self.make_state(
            user_profile_digest={
                "schema_version": 1,
                "nickname": "小林",
                "age_range": "18_plus",
                "user_mode": "adult",
                "usage_goals": ["先安抚再建议"],
                "communication_preferences": ["先短短安抚我，再给一个小步骤"],
                "profile_hints": ["用户遇到压力时习惯先沉默一会儿"],
                "preference_hints": ["用户不喜欢一上来就连环追问"],
                "correction_hints": ["不要直接下结论"],
            }
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("用户画像", parts.user_prompt)
        self.assertIn("先安抚再建议", parts.user_prompt)
        self.assertIn("先短短安抚我，再给一个小步骤", parts.user_prompt)
        self.assertIn("用户遇到压力时习惯先沉默一会儿", parts.user_prompt)
        self.assertIn("用户不喜欢一上来就连环追问", parts.user_prompt)
        self.assertIn("不要直接下结论", parts.user_prompt)
        self.assertNotIn("schema_version", parts.user_prompt)

    def test_prompt_prefers_user_context_pack_over_separate_blocks(self) -> None:
        state = self.make_state(
            session_digest={
                "summary_200chars": "旧的会话摘要不应重复注入。",
                "key_themes": ["旧主题"],
            },
            user_profile_digest={
                "nickname": "小林",
                "usage_goals": ["旧画像目标"],
            },
            user_context_pack={
                "schema_version": 1,
                "active_goal": "理清楚和主管沟通任务边界",
                "conversation_focus": "用户持续讨论职场压力和任务边界。",
                "style_corrections": ["不要直接给模板"],
                "profile_hints": ["重要沟通前会先写提纲"],
                "open_threads": ["如何和主管开口"],
                "retrieved_memory_hints": ["目标记忆：理清楚任务边界"],
                "priority_notes": ["优先围绕当前目标和澄清答案回应"],
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("用户上下文优先级包", parts.user_prompt)
        self.assertIn("当前目标：理清楚和主管沟通任务边界", parts.user_prompt)
        self.assertIn("纠错提示：不要直接给模板", parts.user_prompt)
        self.assertNotIn("会话全景", parts.user_prompt)
        self.assertNotIn("用户画像", parts.user_prompt)
        self.assertNotIn("旧的会话摘要不应重复注入", parts.user_prompt)

    def test_prompt_includes_compact_context_pack_without_raw_json(self) -> None:
        state = self.make_state(
            compact_context_pack={
                "schema_version": 1,
                "event": {
                    "type": "compact_event",
                    "range": {"forgotten_turn_ids": ["turn-1", "turn-2"]},
                },
                "state": {
                    "summary_for_prompt": "用户现在主要在表达生气和堵。",
                    "active_threads": [{"topic": "当前生气", "next_move_hint": "先承接"}],
                    "stale_threads": [{"topic": "在轮下", "reuse_policy": "除非用户主动提起，否则不要复用"}],
                    "user_boundaries": ["用户不喜欢被强行分析"],
                    "interaction_preferences": ["少连续追问"],
                    "safety_context": {"risk_level": "L0", "note": "普通支持"},
                    "time_context_policy": {"timezone": "Asia/Wuhan", "source": "runtime"},
                    "quality_signals": {"recent_repetition_risk": "high"},
                },
            }
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("当前会话压缩状态", parts.user_prompt)
        self.assertIn("用户现在主要在表达生气和堵", parts.user_prompt)
        self.assertIn("当前生气", parts.user_prompt)
        self.assertIn("在轮下", parts.user_prompt)
        self.assertIn("不要复用", parts.user_prompt)
        self.assertIn("用户不喜欢被强行分析", parts.user_prompt)
        self.assertIn("少连续追问", parts.user_prompt)
        self.assertIn("Asia/Wuhan", parts.user_prompt)
        self.assertNotIn("compact_context_pack", parts.user_prompt)
        self.assertNotIn("schema_version", parts.user_prompt)
        self.assertNotIn("forgotten_turn_ids", parts.user_prompt)

    def test_prompt_keeps_compact_context_when_user_context_pack_exists(self) -> None:
        state = self.make_state(
            compact_context_pack={"state": {"summary_for_prompt": "短期压缩状态"}},
            user_context_pack={"active_goal": "先把情绪稳住"},
            session_digest={"summary_200chars": "旧摘要"},
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("当前会话压缩状态", parts.user_prompt)
        self.assertIn("短期压缩状态", parts.user_prompt)
        self.assertIn("用户上下文优先级包", parts.user_prompt)
        self.assertNotIn("会话全景", parts.user_prompt)

    def test_prompt_uses_dynamic_length_guidance_instead_of_fixed_short_range(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(normalized_text="这件事有点复杂，我想让你多说一点，帮我详细展开看看。"),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("不要固定短回复", parts.system_prompt)
        self.assertNotIn("常规对话控制在 120–260 字左右", parts.system_prompt)
        self.assertIn("本轮长度策略", parts.user_prompt)
        self.assertIn("260–520 字", parts.user_prompt)

    def test_prompt_includes_semantic_risk_guidance_for_emotional_metaphor(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                normalized_text="在生活中有一种想死想死的感觉",
                user_text="在生活中有一种想死想死的感觉",
                risk_level="L1",
                route_priority="P2_support",
                semantic_risk={
                    "risk_domain": "general_distress",
                    "risk_expression_type": "emotional_metaphor",
                    "signal_family": ["death_language"],
                    "subject": "self",
                    "literalness": "metaphorical",
                },
            ),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("风险语义层", parts.user_prompt)
        self.assertIn("emotional_metaphor", parts.user_prompt)
        self.assertIn("general_distress", parts.user_prompt)
        self.assertIn("death_language", parts.user_prompt)
        self.assertNotIn("['death_language']", parts.user_prompt)
        self.assertIn("self", parts.user_prompt)
        self.assertIn("metaphorical", parts.user_prompt)
        self.assertIn("不要把情绪隐喻说成自杀意图", parts.user_prompt)
        self.assertIn("不要第一句安全盘问", parts.user_prompt)

    def test_prompt_includes_semantic_risk_guidance_for_non_suicidal_self_injury_urge(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                normalized_text="我控制不住想弄疼自己",
                user_text="我控制不住想弄疼自己",
                risk_level="L2",
                route_priority="P0_immediate_safety",
                semantic_risk={
                    "risk_domain": "non_suicidal_self_injury",
                    "risk_expression_type": "non_suicidal_self_injury_urge",
                    "signal_family": "self_injury_language",
                    "subject": "self",
                    "literalness": "literal",
                },
            ),
            mode="crisis",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("风险语义层", parts.user_prompt)
        self.assertIn("non_suicidal_self_injury_urge", parts.user_prompt)
        self.assertIn("non_suicidal_self_injury", parts.user_prompt)
        self.assertIn("不要把它改写成自杀意图", parts.user_prompt)

    def test_crisis_length_guidance_prefers_response_policy_char_budget(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                normalized_text="我控制不住想弄疼自己",
                user_text="我控制不住想弄疼自己",
                risk_level="L2",
                route_priority="P0_immediate_safety",
                risk_response_policy={"char_budget": {"target": 120, "max": 180}},
            ),
            mode="crisis",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("目标约 120 字，上限 180 字", parts.user_prompt)

    def test_prompt_injects_no_question_ending_strategy(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                risk_response_policy={
                    "ending_style": "reflective_pause",
                    "question_budget": 0,
                    "avoid_question_reason": "previous_turn_ended_with_question",
                    "question_ending_streak": 1,
                }
            ),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("结尾策略", parts.user_prompt)
        self.assertIn("reflective_pause", parts.user_prompt)
        self.assertIn("question_budget=0", parts.user_prompt)
        self.assertIn("不要用问句收尾", parts.user_prompt)
        self.assertIn("问题是可选动作", parts.user_prompt)

    def test_prompt_injects_micro_step_strategy_for_crisis(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(
                risk_level="L3",
                route_priority="P0_immediate_safety",
                risk_response_policy={
                    "ending_style": "micro_step",
                    "question_budget": 1,
                    "allow_question_reason": "immediate_safety_check",
                },
            ),
            mode="crisis",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("micro_step", parts.user_prompt)
        self.assertIn("只给一个低门槛动作", parts.user_prompt)

    def test_prompt_allows_very_short_replies_for_light_chat(self) -> None:
        parts = build_dialogue_prompt_parts(
            self.make_state(normalized_text="哈哈", user_text="哈哈"),
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("本轮长度策略", parts.user_prompt)
        self.assertIn("20–80 字", parts.user_prompt)

    def test_prompt_prioritizes_current_turn_after_recent_risk_topic_shift(self) -> None:
        state = self.make_state(
            normalized_text="你觉得荣格是个什么样的人",
            user_text="你觉得荣格是个什么样的人",
            recent_messages=[{"role": "user", "content": "有点想死", "risk_level": "L2"}],
            risk_level="L0",
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("当前轮次优先级", parts.user_prompt)
        self.assertIn("历史里的风险表达不要说成用户现在又说", parts.user_prompt)
        self.assertIn("风险后回流", parts.user_prompt)
        self.assertIn("先回应当前话题", parts.user_prompt)
        self.assertIn("不要主动安全盘问", parts.user_prompt)
        self.assertIn("用户刚刚说：你觉得荣格是个什么样的人", parts.user_prompt)


    def test_prompt_includes_conversation_move_policy_as_readable_block(self) -> None:
        state = self.make_state(
            normalized_text="在轮下，记得吗",
            user_text="在轮下，记得吗",
            conversation_move_policy={
                "conversation_move": "continue_thread",
                "topic_anchor": "literary/metaphor",
                "style_variation": "fixed_opening_avoidance",
                "correction_state": {"active": False},
                "psychologizing_risk": "medium",
                "button_style": "topic_continue",
                "handling": "先接住《在轮下》这个锚点，不把它改写成心理分析。",
                "opening_style": "直接回应用户刚刚的词，不复用固定开头。",
                "structure_mode": "single_paragraph",
                "structure_style": "single_paragraph，避免复用上一轮的两段式整理+追问。",
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("本轮对话动作", parts.user_prompt)
        self.assertIn("用户锚点", parts.user_prompt)
        self.assertIn("处理方式", parts.user_prompt)
        self.assertIn("开头方式", parts.user_prompt)
        self.assertIn("结构方式", parts.user_prompt)
        self.assertIn("按钮风格", parts.user_prompt)
        self.assertIn("continue_thread", parts.user_prompt)
        self.assertIn("literary/metaphor", parts.user_prompt)
        self.assertIn("single_paragraph", parts.user_prompt)
        self.assertIn("两段式整理+追问", parts.user_prompt)
        self.assertIn("topic_continue", parts.user_prompt)
        self.assertIn("不要把 topic_continue", parts.user_prompt)
        self.assertNotIn("style_variation", parts.user_prompt)
        self.assertNotIn("correction_state", parts.user_prompt)

    def test_prompt_warns_cultural_anchor_should_not_fabricate_details(self) -> None:
        state = self.make_state(
            normalized_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
            user_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "literary",
                "anchor_value": "德米安",
                "anchor_handling": "treat_as_topic",
                "handling": "把用户提到的锚点当作真实话题继续聊，轻轻连接处境但不心理化。",
                "button_style": "topic_continue",
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("不确定", parts.user_prompt)
        self.assertIn("只回应用户给出的线索", parts.user_prompt)
        self.assertIn("不要虚构", parts.user_prompt)

    def test_prompt_includes_anchor_evidence_without_raw_json(self) -> None:
        state = self.make_state(
            normalized_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
            user_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "literary",
                "anchor_value": "德米安",
                "anchor_evidence": {
                    "anchor_type": "literary",
                    "anchor_value": "德米安",
                    "surface_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
                    "confidence": "explicit",
                    "user_clues": [
                        {"text": "没读过", "kind": "knowledge_boundary", "source": "current_user"},
                        {"text": "自我寻找", "kind": "theme", "source": "current_user"},
                    ],
                    "allowed_basis": ["user_clues", "recent_context"],
                    "forbidden_claims": ["plot_detail", "character_detail", "author_intent", "ending"],
                    "response_mode": "echo_user_clue",
                },
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("文化锚点证据", parts.user_prompt)
        self.assertIn("德米安", parts.user_prompt)
        self.assertIn("没读过", parts.user_prompt)
        self.assertIn("自我寻找", parts.user_prompt)
        self.assertIn("不要百科介绍", parts.user_prompt)
        self.assertIn("允许依据", parts.user_prompt)
        self.assertIn("禁止声称", parts.user_prompt)
        self.assertNotIn("anchor_evidence", parts.user_prompt)
        self.assertNotIn("user_clues", parts.user_prompt)

    def test_prompt_warns_not_to_revive_stale_recent_anchor(self) -> None:
        state = self.make_state(
            normalized_text="我感到很生气",
            user_text="我感到很生气",
            conversation_move_policy={
                "conversation_move": "ordinary_chat",
                "topic_anchor": "none",
                "anchor_value": "",
                "anchor_handling": "avoid_psychologizing",
                "handling": "先回应用户当前说的生气，不把旧锚点带回来。",
                "suppressed_recent_anchors": ["在轮下"],
                "stale_anchor_handling": "最近出现过这些锚点，但用户本轮没有主动提；不要主动带回。",
                "button_style": "user_voice",
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("旧锚点提醒", parts.user_prompt)
        self.assertIn("在轮下", parts.user_prompt)
        self.assertIn("用户本轮没有主动提", parts.user_prompt)
        self.assertIn("不要主动带回", parts.user_prompt)
        self.assertNotIn("suppressed_recent_anchors", parts.user_prompt)

    def test_prompt_renders_intent_lanes_voice_contract_and_adaptation_naturally(self) -> None:
        state = self.make_state(
            normalized_text="我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。",
            user_text="我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。",
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "literary",
                "anchor_value": "德米安",
                "primary_lane": "self_reference",
                "intent_lanes": [
                    {
                        "id": "lane_1",
                        "kind": "cultural_anchor",
                        "anchor_type": "literary",
                        "anchor_value": "德米安",
                        "priority": "secondary",
                        "handling": "do_not_expand_work_detail",
                    },
                    {
                        "id": "lane_2",
                        "kind": "self_reference",
                        "user_clues": ["找自己", "有点像我"],
                        "priority": "primary",
                        "handling": "respond_to_user_clue",
                    },
                    {
                        "id": "lane_3",
                        "kind": "boundary",
                        "user_clues": ["别又开始分析我"],
                        "priority": "blocking_style_constraint",
                        "handling": "lower_analysis_depth",
                    },
                ],
                "ningyu_voice_contract": {
                    "voice_mode": "anchored_companion",
                    "analysis_depth": "none",
                    "question_budget": 0,
                    "sentence_budget": "2-4",
                    "opening_preference": "echo_user_words",
                    "closing_preference": "pause",
                    "humor_allowed": False,
                    "avoid_patterns": ["听起来你", "这说明你", "你可能是在"],
                },
                "adaptation_state": {
                    "avoid_analysis_turns": 2,
                    "avoid_questions_turns": 0,
                    "avoid_safety_check_turns": 0,
                    "prefer_direct_anchor_response_turns": 2,
                    "last_correction_type": "too_psychological",
                },
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("本轮主线", parts.user_prompt)
        self.assertIn("找自己", parts.user_prompt)
        self.assertIn("可轻触的线", parts.user_prompt)
        self.assertIn("德米安", parts.user_prompt)
        self.assertIn("不要展开", parts.user_prompt)
        self.assertIn("不要补作品情节", parts.user_prompt)
        self.assertIn("宁语声线", parts.user_prompt)
        self.assertIn("2-4 句", parts.user_prompt)
        self.assertIn("最多 0 个问题", parts.user_prompt)
        self.assertIn("短期适配", parts.user_prompt)
        self.assertIn("降低分析深度", parts.user_prompt)
        self.assertNotIn("intent_lanes", parts.user_prompt)
        self.assertNotIn("ningyu_voice_contract", parts.user_prompt)
        self.assertNotIn("adaptation_state", parts.user_prompt)

    def test_prompt_renders_light_common_sense_allowed_basis(self) -> None:
        state = self.make_state(
            normalized_text="荣格",
            user_text="荣格",
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "philosophical",
                "anchor_value": "荣格",
                "anchor_evidence": {
                    "anchor_type": "philosophical",
                    "anchor_value": "荣格",
                    "confidence": "explicit",
                    "user_clues": [],
                    "allowed_basis": ["user_clues", "recent_context", "light_common_sense"],
                    "forbidden_claims": ["plot_detail", "author_intent"],
                    "response_mode": "light_context_only",
                },
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("允许依据", parts.user_prompt)
        self.assertIn("轻常识", parts.user_prompt)
        self.assertIn("不展开讲座", parts.user_prompt)

    def test_prompt_guides_no_knowledge_claim_for_uncertain_quote(self) -> None:
        state = self.make_state(
            normalized_text="我记不清原句了，大概是说人一直被什么东西推着走",
            user_text="我记不清原句了，大概是说人一直被什么东西推着走",
            conversation_move_policy={
                "conversation_move": "respond_to_anchor",
                "topic_anchor": "quote",
                "anchor_value": "",
                "anchor_evidence": {
                    "anchor_type": "quote",
                    "anchor_value": "",
                    "surface_text": "我记不清原句了，大概是说人一直被什么东西推着走",
                    "confidence": "weak",
                    "user_clues": [
                        {"text": "记不清原句", "kind": "knowledge_boundary", "source": "current_user"},
                        {"text": "被什么东西推着走", "kind": "image", "source": "current_user"},
                    ],
                    "allowed_basis": ["user_clues", "recent_context"],
                    "forbidden_claims": ["quote_attribution", "author_intent"],
                    "response_mode": "no_knowledge_claim",
                },
            },
        )

        parts = build_dialogue_prompt_parts(
            state,
            mode="companion",
            response_contract={"allow_rag": False},
            examples_text="",
            memory_text="",
        )

        self.assertIn("不要追出处", parts.user_prompt)
        self.assertIn("不要硬猜作者或原句", parts.user_prompt)


if __name__ == "__main__":
    unittest.main()
