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


if __name__ == "__main__":
    unittest.main()
