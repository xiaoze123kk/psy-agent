from __future__ import annotations

import logging

import httpx

from app.services.tooling import _clean_text


logger = logging.getLogger(__name__)

_WTTR_URL = "https://wttr.in"
_DEFAULT_TIMEOUT = 5.0
_DEFAULT_CITY = "Beijing"


def get_weather(city: str = _DEFAULT_CITY, *, timeout_seconds: float = _DEFAULT_TIMEOUT) -> tuple[str, str | None]:
    """Fetch current weather for a city from wttr.in.

    Returns (weather_text, error). error is None on success.
    """
    cleaned_city = _clean_text(city, limit=40) or _DEFAULT_CITY
    try:
        resp = httpx.get(
            f"{_WTTR_URL}/{cleaned_city}",
            params={"format": "%C+%t+%h+%w", "lang": "zh"},
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if text and len(text) <= 120:
            return text, None
        return _clean_text(text, limit=120), None
    except httpx.TimeoutException:
        logger.warning("Weather fetch timed out for city: %s", cleaned_city)
        return "", "timeout"
    except Exception:
        logger.warning("Weather fetch failed for city: %s", cleaned_city)
        return "", "network_error"
