from __future__ import annotations

import asyncio
import unittest

from app.graphs.nodes.response_nodes import clarification_response
from app.graphs.state import AgentState


def _run(coro):
    return asyncio.run(coro)


class ConversationQualityClarificationTests(unittest.TestCase):
    def test_clarification_reply_is_short_and_contains_only_one_question(self) -> None:
        state: AgentState = {
            "user_text": "有点乱",
            "normalized_text": "有点乱",
            "clarification_needed": True,
            "clarification_reason": "ambiguous_need",
            "goal_state": {"current_goal": "理清楚和主管沟通任务边界"},
        }

        result = _run(clarification_response(state))
        assistant_text = result["assistant_text"]

        self.assertLessEqual(len(assistant_text), 80)
        self.assertEqual(assistant_text.count("？") + assistant_text.count("?"), 1)
        self.assertNotIn("第一", assistant_text)
        self.assertNotIn("第二", assistant_text)
        self.assertEqual(result["suggested_actions"], [])


if __name__ == "__main__":
    unittest.main()
