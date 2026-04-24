from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model
        self.timeout_seconds = settings.deepseek_timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.6) -> str | None:
        if not self.is_configured:
            return None

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 420,
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


deepseek_client = DeepSeekClient()
