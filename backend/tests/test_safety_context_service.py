from __future__ import annotations

import unittest

from app.services.safety_context_service import build_safety_context_pack, sanitize_safety_context_text


class SafetyContextServiceTests(unittest.TestCase):
    def test_sanitize_filters_contacts_and_method_details(self) -> None:
        text = "用户之前说刀在床边，手机号 138 0000 0000，姐姐能陪。"

        sanitized = sanitize_safety_context_text(text, risk_level="L3")

        self.assertNotIn("刀", sanitized)
        self.assertNotIn("138", sanitized)
        self.assertIn("姐姐", sanitized)
        self.assertIn("已概括安全风险细节", sanitized)

    def test_pack_keeps_safe_memory_types_only(self) -> None:
        pack = build_safety_context_pack(
            risk_level="L3",
            retrieved_memories=[
                {
                    "memory_type": "preference",
                    "summary": "用户不喜欢被命令，偏好短句。",
                    "visibility": "user_visible",
                },
                {
                    "memory_type": "relationship",
                    "content": "姐姐可以陪用户一会儿，电话 13800000000。",
                    "visibility": "user_visible",
                },
                {
                    "memory_type": "state",
                    "content": "普通状态记忆不应进入高风险安全包。",
                    "visibility": "user_visible",
                },
            ],
            session_digest={"summary_200chars": "最近夜间孤独时风险升高。"},
            user_context_pack={"style_corrections": ["不要一上来推热线"]},
        )

        self.assertEqual(pack["schema_version"], 1)
        self.assertIn("不要一上来推热线", pack["style_corrections"])
        self.assertTrue(any("不喜欢被命令" in item for item in pack["memory_hints"]))
        self.assertTrue(any("姐姐" in item for item in pack["support_hints"]))
        self.assertFalse(any("普通状态记忆" in item for item in pack["memory_hints"]))
        self.assertNotIn("138", str(pack))

    def test_low_risk_pack_is_empty(self) -> None:
        pack = build_safety_context_pack(
            risk_level="L1",
            retrieved_memories=[{"memory_type": "preference", "summary": "偏好短句"}],
            session_digest={},
            user_context_pack={},
        )

        self.assertEqual(pack, {})


if __name__ == "__main__":
    unittest.main()
