from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)
STREAM_DONE = object()


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model
        self.chat_model = settings.deepseek_chat_model
        self.knowledge_model = settings.deepseek_knowledge_model
        self.timeout_seconds = settings.deepseek_timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.6,
        max_tokens: int = 420,
    ) -> str | None:
        if not self.is_configured:
            return None

        payload: dict[str, Any] = {
            "model": model or self.chat_model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
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
            logger.warning("DeepSeek chat request failed: %s", exc)
            return None

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            return None
        return content.strip() or None

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
        temperature: float = 0.6,
        max_tokens: int = 420,
    ) -> AsyncIterator[str]:
        if not self.is_configured:
            return

        payload: dict[str, Any] = {
            "model": model or self.chat_model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
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
