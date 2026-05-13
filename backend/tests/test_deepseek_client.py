from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.config import load_settings
from app.services.deepseek_client import ChatCompletionResult, DeepSeekClient, STREAM_DONE


def make_completion(
    *,
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[dict] | None = None,
) -> ChatCompletionResult:
    message = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return ChatCompletionResult(
        content=content,
        finish_reason=finish_reason,
        message=message,
        tool_calls=tool_calls or [],
    )


def make_tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeAsyncClient:
    responses: list[dict] = []
    requests: list[dict] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.__class__.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.__class__.responses.pop(0))


class FakeToolLoopClient(DeepSeekClient):
    def __init__(self, completions: list[ChatCompletionResult | None]) -> None:
        super().__init__()
        self.api_key = "test-key"
        self.completions = completions
        self.requests: list[dict] = []

    async def chat_completion(self, messages, **kwargs):
        self.requests.append({"messages": [dict(message) for message in messages], **kwargs})
        return self.completions.pop(0)


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

    def test_chat_payload_can_include_tools_and_tool_choice(self) -> None:
        client = DeepSeekClient()
        client.model = "deepseek-v4-pro"
        client.chat_model = "deepseek-v4-pro"
        client.chat_temperature = 0.75
        client.chat_max_tokens = 420
        client.thinking_enabled = False
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge",
                    "description": "Search approved mental health knowledge.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        payload = client._chat_payload(
            [{"role": "user", "content": "hello"}],
            tools=tools,
            tool_choice="auto",
        )

        self.assertEqual(payload["tools"], tools)
        self.assertEqual(payload["tool_choice"], "auto")

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


class DeepSeekClientCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeAsyncClient.responses = []
        FakeAsyncClient.requests = []

    async def test_chat_completion_parses_plain_message(self) -> None:
        FakeAsyncClient.responses = [
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ]
            }
        ]
        client = DeepSeekClient()
        client.api_key = "test-key"

        with patch("app.services.deepseek_client.httpx.AsyncClient", FakeAsyncClient):
            result = await client.chat_completion([{"role": "user", "content": "hi"}])

        self.assertIsNotNone(result)
        self.assertEqual(result.content, "hello")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.tool_calls, [])

    async def test_chat_completion_parses_multiple_tool_calls(self) -> None:
        tool_calls = [
            make_tool_call("call-1", "search_knowledge", '{"query": "stress"}'),
            make_tool_call("call-2", "get_mood_trend", '{"range": "7d"}'),
        ]
        FakeAsyncClient.responses = [
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        },
                    }
                ]
            }
        ]
        client = DeepSeekClient()
        client.api_key = "test-key"
        tools = [{"type": "function", "function": {"name": "search_knowledge"}}]

        with patch("app.services.deepseek_client.httpx.AsyncClient", FakeAsyncClient):
            result = await client.chat_completion(
                [{"role": "user", "content": "hi"}],
                tools=tools,
                tool_choice="auto",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.finish_reason, "tool_calls")
        self.assertEqual([call["id"] for call in result.tool_calls], ["call-1", "call-2"])
        self.assertEqual(FakeAsyncClient.requests[0]["json"]["tools"], tools)
        self.assertEqual(FakeAsyncClient.requests[0]["json"]["tool_choice"], "auto")


class DeepSeekClientToolLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_with_tools_executes_one_tool_then_returns_final_text(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[make_tool_call("call-1", "search_knowledge", '{"query": "stress"}')],
                ),
                make_completion(content="Here is a grounded answer.", finish_reason="stop"),
            ]
        )

        async def search_knowledge(arguments):
            return {"items": [{"title": arguments["query"]}]}

        result = await client.chat_with_tools(
            [{"role": "user", "content": "tell me about stress"}],
            tools=[{"type": "function", "function": {"name": "search_knowledge"}}],
            tool_handlers={"search_knowledge": search_knowledge},
        )

        self.assertEqual(result.content, "Here is a grounded answer.")
        self.assertEqual(len(result.tool_events), 1)
        self.assertEqual(result.tool_events[0].status, "completed")
        self.assertEqual(result.messages[2]["role"], "tool")
        self.assertIn('"items"', result.messages[2]["content"])
        self.assertEqual(len(client.requests), 2)
        self.assertIs(client.requests[0]["thinking_enabled"], False)

    async def test_chat_with_tools_executes_multiple_tool_calls_in_order(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    finish_reason="tool_calls",
                    tool_calls=[
                        make_tool_call("call-1", "first_tool", '{"value": 1}'),
                        make_tool_call("call-2", "second_tool", '{"value": 2}'),
                    ],
                ),
                make_completion(content="done"),
            ]
        )
        order: list[str] = []

        def first_tool(arguments):
            order.append(f"first:{arguments['value']}")
            return "first-result"

        def second_tool(arguments):
            order.append(f"second:{arguments['value']}")
            return "second-result"

        result = await client.chat_with_tools(
            [{"role": "user", "content": "run tools"}],
            tools=[],
            tool_handlers={"first_tool": first_tool, "second_tool": second_tool},
        )

        self.assertEqual(result.content, "done")
        self.assertEqual(order, ["first:1", "second:2"])
        self.assertEqual([event.name for event in result.tool_events], ["first_tool", "second_tool"])
        self.assertEqual([message["tool_call_id"] for message in result.messages if message["role"] == "tool"], ["call-1", "call-2"])

    async def test_chat_with_tools_handles_unknown_tool(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    finish_reason="tool_calls",
                    tool_calls=[make_tool_call("call-1", "unknown_tool", '{"query": "stress"}')],
                ),
                make_completion(content="I cannot use that tool."),
            ]
        )

        result = await client.chat_with_tools(
            [{"role": "user", "content": "run unknown"}],
            tools=[],
            tool_handlers={},
        )

        self.assertEqual(result.content, "I cannot use that tool.")
        self.assertEqual(result.tool_events[0].status, "error")
        self.assertEqual(result.tool_events[0].error, "unknown_tool")
        self.assertIn("unknown_tool", result.messages[2]["content"])

    async def test_chat_with_tools_handles_invalid_json_arguments(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    finish_reason="tool_calls",
                    tool_calls=[make_tool_call("call-1", "search_knowledge", "not-json")],
                ),
                make_completion(content="Please try again."),
            ]
        )

        result = await client.chat_with_tools(
            [{"role": "user", "content": "bad args"}],
            tools=[],
            tool_handlers={"search_knowledge": lambda arguments: "unused"},
        )

        self.assertEqual(result.content, "Please try again.")
        self.assertEqual(result.tool_events[0].error, "invalid_arguments")
        self.assertIn("invalid_arguments", result.messages[2]["content"])

    async def test_chat_with_tools_handles_handler_exception_without_leaking_details(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    finish_reason="tool_calls",
                    tool_calls=[make_tool_call("call-1", "search_knowledge", '{"query": "stress"}')],
                ),
                make_completion(content="I hit a tool issue, but we can continue."),
            ]
        )

        def failing_handler(arguments):
            del arguments
            raise RuntimeError("secret database password")

        result = await client.chat_with_tools(
            [{"role": "user", "content": "tool fails"}],
            tools=[],
            tool_handlers={"search_knowledge": failing_handler},
        )

        self.assertEqual(result.content, "I hit a tool issue, but we can continue.")
        self.assertEqual(result.tool_events[0].error, "handler_error")
        self.assertIn("handler_error", result.messages[2]["content"])
        self.assertNotIn("secret database password", result.messages[2]["content"])
        self.assertNotIn("secret database password", str(result.tool_events))

    async def test_chat_with_tools_stops_when_max_tool_rounds_is_exceeded(self) -> None:
        client = FakeToolLoopClient(
            [
                make_completion(
                    finish_reason="tool_calls",
                    tool_calls=[make_tool_call("call-1", "search_knowledge", '{"query": "stress"}')],
                )
            ]
        )

        result = await client.chat_with_tools(
            [{"role": "user", "content": "loop"}],
            tools=[],
            tool_handlers={"search_knowledge": lambda arguments: "unused"},
            max_tool_rounds=0,
        )

        self.assertIsNone(result.content)
        self.assertEqual(result.finish_reason, "max_tool_rounds_exceeded")
        self.assertEqual(result.tool_events[0].error, "max_tool_rounds_exceeded")
        self.assertFalse(any(message["role"] == "tool" for message in result.messages))

    async def test_chat_with_tools_rejects_explicit_thinking_mode(self) -> None:
        client = FakeToolLoopClient([])

        with self.assertRaises(ValueError):
            await client.chat_with_tools(
                [{"role": "user", "content": "hello"}],
                tools=[],
                tool_handlers={},
                thinking_enabled=True,
            )
