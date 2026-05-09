from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.config import load_settings
from app.services.deepseek_client import DeepSeekClient, STREAM_DONE


class DeepSeekClientStreamingTests(unittest.TestCase):
    def test_default_deepseek_settings_use_v4_pro(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.deepseek_model, "deepseek-v4-pro")
        self.assertEqual(loaded.deepseek_chat_model, "deepseek-v4-pro")
        self.assertEqual(loaded.deepseek_knowledge_model, "deepseek-v4-pro")
        self.assertEqual(loaded.deepseek_chat_temperature, 0.75)
        self.assertEqual(loaded.deepseek_chat_max_tokens, 420)
        self.assertEqual(loaded.deepseek_knowledge_temperature, 0.3)
        self.assertEqual(loaded.deepseek_knowledge_max_tokens, 760)
        self.assertFalse(loaded.deepseek_thinking_enabled)

    def test_chat_payload_uses_v4_pro_defaults_and_disables_thinking(self) -> None:
        client = DeepSeekClient()
        client.model = "deepseek-v4-pro"
        client.chat_model = "deepseek-v4-pro"
        client.chat_temperature = 0.75
        client.chat_max_tokens = 420
        client.thinking_enabled = False

        payload = client._chat_payload([{"role": "user", "content": "hello"}])

        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["temperature"], 0.75)
        self.assertEqual(payload["max_tokens"], 420)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("top_p", payload)
        self.assertNotIn("stream", payload)

    def test_stream_payload_uses_same_model_and_stream_flag(self) -> None:
        client = DeepSeekClient()
        client.model = "deepseek-v4-pro"
        client.chat_model = "deepseek-v4-pro"
        client.chat_temperature = 0.75
        client.chat_max_tokens = 420
        client.thinking_enabled = False

        payload = client._chat_payload([{"role": "user", "content": "hello"}], stream=True)

        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("top_p", payload)

    def test_knowledge_payload_can_use_knowledge_sampling_config(self) -> None:
        client = DeepSeekClient()
        client.knowledge_model = "deepseek-v4-pro"
        client.knowledge_temperature = 0.3
        client.knowledge_max_tokens = 760
        client.thinking_enabled = False

        payload = client._chat_payload(
            [{"role": "user", "content": "hello"}],
            model=client.knowledge_model,
            temperature=client.knowledge_temperature,
            max_tokens=client.knowledge_max_tokens,
        )

        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(payload["max_tokens"], 760)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("top_p", payload)

    def test_stream_delta_parser_reads_content_deltas(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"hello"}}]}'

        self.assertEqual(DeepSeekClient._stream_delta_from_line(line), "hello")

    def test_stream_delta_parser_stops_on_done(self) -> None:
        self.assertIs(DeepSeekClient._stream_delta_from_line("data: [DONE]"), STREAM_DONE)

    def test_stream_delta_parser_ignores_empty_and_non_content_lines(self) -> None:
        self.assertIsNone(DeepSeekClient._stream_delta_from_line(""))
        self.assertIsNone(DeepSeekClient._stream_delta_from_line(": keepalive"))
        self.assertIsNone(DeepSeekClient._stream_delta_from_line('data: {"choices":[{"delta":{}}]}'))
        self.assertIsNone(DeepSeekClient._stream_delta_from_line("data: not-json"))
