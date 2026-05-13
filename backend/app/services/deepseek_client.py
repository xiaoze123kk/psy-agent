from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)
STREAM_DONE = object()
DEFAULT_MAX_TOOL_ROUNDS = 3
DEFAULT_TOOL_RESULT_MAX_CHARS = 4000

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str | None
    finish_reason: str | None
    message: dict[str, Any]
    tool_calls: list[dict[str, Any]]


@dataclass(frozen=True)
class ToolExecutionEvent:
    tool_call_id: str
    name: str
    arguments: dict[str, Any] | None
    status: str
    error: str | None = None


@dataclass(frozen=True)
class ToolChatResult:
    content: str | None
    tool_events: list[ToolExecutionEvent]
    finish_reason: str | None
    messages: list[dict[str, Any]]


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model
        self.chat_model = settings.deepseek_chat_model
        self.knowledge_model = settings.deepseek_knowledge_model
        self.timeout_seconds = settings.deepseek_timeout_seconds
        self.chat_temperature = settings.deepseek_chat_temperature
        self.chat_max_tokens = settings.deepseek_chat_max_tokens
        self.knowledge_temperature = settings.deepseek_knowledge_temperature
        self.knowledge_max_tokens = settings.deepseek_knowledge_max_tokens
        self.thinking_enabled = settings.deepseek_thinking_enabled

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _chat_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking_enabled: bool | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_thinking_enabled = self.thinking_enabled if thinking_enabled is None else thinking_enabled
        payload: dict[str, Any] = {
            "model": model or self.chat_model or self.model,
            "messages": messages,
            "temperature": self.chat_temperature if temperature is None else temperature,
            "max_tokens": self.chat_max_tokens if max_tokens is None else max_tokens,
            "thinking": {"type": "enabled" if effective_thinking_enabled else "disabled"},
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if stream:
            payload["stream"] = True
        return payload

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking_enabled: bool | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatCompletionResult | None:
        if not self.is_configured:
            return None

        payload = self._chat_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            thinking_enabled=thinking_enabled,
            tools=tools,
            tool_choice=tool_choice,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("DeepSeek chat completion request failed: %s", exc)
            return None

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None

        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        raw_message = choice.get("message") or {}
        if not isinstance(raw_message, dict):
            return None

        message = dict(raw_message)
        content = message.get("content")
        tool_calls = message.get("tool_calls") or []
        if not isinstance(content, str):
            content = None
        if not isinstance(tool_calls, list):
            tool_calls = []

        finish_reason = choice.get("finish_reason")
        return ChatCompletionResult(
            content=content,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            message=message,
            tool_calls=[dict(tool_call) for tool_call in tool_calls if isinstance(tool_call, dict)],
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> str | None:
        completion = await self.chat_completion(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            thinking_enabled=thinking_enabled,
        )
        if completion is None or completion.content is None:
            return None
        return completion.content.strip() or None

    @staticmethod
    def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        history_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        if isinstance(message.get("tool_calls"), list):
            history_message["tool_calls"] = message["tool_calls"]
        if message.get("reasoning_content") is not None:
            history_message["reasoning_content"] = message["reasoning_content"]
        return history_message

    @staticmethod
    def _tool_error_content(code: str) -> str:
        return json.dumps(
            {
                "error": {
                    "code": code,
                    "message": "Tool call failed.",
                }
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _serialize_tool_result(result: object, *, max_chars: int) -> str:
        if isinstance(result, str):
            content = result
        else:
            content = json.dumps(result, ensure_ascii=False, default=str)

        if len(content) > max_chars:
            return content[:max(max_chars, 0)] + "...[truncated]"
        return content

    @staticmethod
    def _parse_tool_arguments(raw_arguments: object) -> dict[str, Any] | None:
        if raw_arguments is None or raw_arguments == "":
            return {}
        if not isinstance(raw_arguments, str):
            return None
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        tool_handlers: dict[str, ToolHandler],
        tool_result_max_chars: int,
    ) -> tuple[ToolExecutionEvent, dict[str, Any]]:
        tool_call_id = str(tool_call.get("id") or "")
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        name = str(function.get("name") or "")
        arguments = self._parse_tool_arguments(function.get("arguments"))

        def tool_message(content: str) -> dict[str, Any]:
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }

        if arguments is None:
            event = ToolExecutionEvent(
                tool_call_id=tool_call_id,
                name=name,
                arguments=None,
                status="error",
                error="invalid_arguments",
            )
            return event, tool_message(self._tool_error_content("invalid_arguments"))

        handler = tool_handlers.get(name)
        if handler is None:
            event = ToolExecutionEvent(
                tool_call_id=tool_call_id,
                name=name,
                arguments=arguments,
                status="error",
                error="unknown_tool",
            )
            return event, tool_message(self._tool_error_content("unknown_tool"))

        try:
            result = handler(arguments)
            if isawaitable(result):
                result = await result
            content = self._serialize_tool_result(result, max_chars=tool_result_max_chars)
        except Exception:
            logger.warning("DeepSeek tool handler failed: %s", name)
            event = ToolExecutionEvent(
                tool_call_id=tool_call_id,
                name=name,
                arguments=arguments,
                status="error",
                error="handler_error",
            )
            return event, tool_message(self._tool_error_content("handler_error"))

        event = ToolExecutionEvent(
            tool_call_id=tool_call_id,
            name=name,
            arguments=arguments,
            status="completed",
            error=None,
        )
        return event, tool_message(content)

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, ToolHandler],
        tool_choice: str | dict[str, Any] | None = "auto",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking_enabled: bool | None = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        tool_result_max_chars: int = DEFAULT_TOOL_RESULT_MAX_CHARS,
    ) -> ToolChatResult:
        if thinking_enabled is True:
            raise ValueError("chat_with_tools does not support thinking mode yet.")

        working_messages = [dict(message) for message in messages]
        tool_events: list[ToolExecutionEvent] = []
        tool_rounds = 0

        while True:
            completion = await self.chat_completion(
                working_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                thinking_enabled=False,
                tools=tools,
                tool_choice=tool_choice,
            )
            if completion is None:
                return ToolChatResult(
                    content=None,
                    tool_events=tool_events,
                    finish_reason="request_failed",
                    messages=working_messages,
                )

            working_messages.append(self._assistant_message_for_history(completion.message))
            if not completion.tool_calls:
                content = completion.content.strip() if completion.content else None
                return ToolChatResult(
                    content=content or None,
                    tool_events=tool_events,
                    finish_reason=completion.finish_reason,
                    messages=working_messages,
                )

            if tool_rounds >= max_tool_rounds:
                for tool_call in completion.tool_calls:
                    function = tool_call.get("function") if isinstance(tool_call, dict) else {}
                    if not isinstance(function, dict):
                        function = {}
                    tool_events.append(
                        ToolExecutionEvent(
                            tool_call_id=str(tool_call.get("id") or ""),
                            name=str(function.get("name") or ""),
                            arguments=self._parse_tool_arguments(function.get("arguments")),
                            status="error",
                            error="max_tool_rounds_exceeded",
                        )
                    )
                return ToolChatResult(
                    content=None,
                    tool_events=tool_events,
                    finish_reason="max_tool_rounds_exceeded",
                    messages=working_messages,
                )

            tool_rounds += 1
            for tool_call in completion.tool_calls:
                event, tool_message = await self._execute_tool_call(
                    tool_call,
                    tool_handlers=tool_handlers,
                    tool_result_max_chars=tool_result_max_chars,
                )
                tool_events.append(event)
                working_messages.append(tool_message)

    @staticmethod
    def _stream_delta_from_line(line: str) -> str | object | None:
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            return None

        data = line[5:].strip()
        if data == "[DONE]":
            return STREAM_DONE

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("Ignoring malformed DeepSeek stream line: %s", line)
            return None

        choices = payload.get("choices") or []
        if not choices:
            return None

        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if not isinstance(content, str) or not content:
            return None
        return content

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> AsyncIterator[str]:
        if not self.is_configured:
            return

        payload = self._chat_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            thinking_enabled=thinking_enabled,
            stream=True,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        delta = self._stream_delta_from_line(line)
                        if delta is STREAM_DONE:
                            break
                        if isinstance(delta, str):
                            yield delta
        except httpx.HTTPError as exc:
            logger.warning("DeepSeek streaming chat request failed: %s", exc)
            return


deepseek_client = DeepSeekClient()
