from __future__ import annotations

import unittest

from app.services.deepseek_client import DeepSeekClient, STREAM_DONE


class DeepSeekClientStreamingTests(unittest.TestCase):
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
