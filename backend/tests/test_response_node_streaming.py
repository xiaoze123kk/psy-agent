from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.graphs.nodes import response_nodes


async def fake_action_stream(messages):
    del messages
    yield "Hel"
    yield "lo\n-"
    yield "--\nKeep going\n"


class ResponseNodeStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_reply_writes_visible_body_only(self) -> None:
        events: list[dict[str, object]] = []

        with (
            patch("app.graphs.nodes.response_nodes.get_stream_writer", return_value=events.append),
            patch.object(response_nodes.deepseek_client, "stream_chat", new=fake_action_stream),
            patch.object(response_nodes.deepseek_client, "chat", new=AsyncMock(return_value=None)) as chat,
        ):
            body, actions = await response_nodes._streamed_reply_with_actions(
                [{"role": "user", "content": "hello"}]
            )

        self.assertEqual(body, "Hello")
        self.assertEqual(actions, ["Keep going"])
        self.assertEqual("".join(str(event["text"]) for event in events), "Hello")
        self.assertNotIn("---", str(events))
        self.assertNotIn("Keep going", str(events))
        chat.assert_not_awaited()

    async def test_streamed_reply_falls_back_when_no_writer_exists(self) -> None:
        with (
            patch("app.graphs.nodes.response_nodes.get_stream_writer", side_effect=RuntimeError),
            patch.object(response_nodes.deepseek_client, "chat", new=AsyncMock(return_value="Fallback\n---\nAction")),
        ):
            body, actions = await response_nodes._streamed_reply_with_actions(
                [{"role": "user", "content": "hello"}]
            )

        self.assertEqual(body, "Fallback")
        self.assertEqual(actions, ["Action"])
