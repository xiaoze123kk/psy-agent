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
                "emotional_arc": "紧绷 -> 疲惫 -> 稍微松动",
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
            memory_text="无",
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
            memory_text="无",
        )

        self.assertNotIn("会话全景", parts.user_prompt)


if __name__ == "__main__":
    unittest.main()
