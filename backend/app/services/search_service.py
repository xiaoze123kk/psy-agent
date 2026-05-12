from __future__ import annotations

import logging
from dataclasses import dataclass

from duckduckgo_search import DDGS

from app.services.tooling import _clean_text, _clamp_int


logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 3
MAX_SNIPPET_CHARS = 280
SEARCH_REGION = "cn"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def _ddg_text(query: str, *, region: str, max_results: int) -> list[dict[str, object]]:
    """Thin wrapper over DDGS for testability via patching."""
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, region=region, max_results=max_results))
    return [dict(item) for item in raw if isinstance(item, dict)]


def search_web(query: str, *, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
    """Search DuckDuckGo for the given query, returning cleaned, deduplicated results.

    Returns an empty list on any error (network, parse, etc.).
    """
    cleaned_query = _clean_text(query, limit=240)
    if not cleaned_query:
        return []

    limit = _clamp_int(max_results, default=DEFAULT_MAX_RESULTS, minimum=1, maximum=5)

    try:
        raw_items = _ddg_text(cleaned_query, region=SEARCH_REGION, max_results=limit * 3)
    except Exception:
        logger.warning("DuckDuckGo search failed for query: %s", cleaned_query[:80])
        return []

    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), limit=80)
        url = _clean_text(item.get("href") or item.get("url"), limit=500)
        snippet = _clean_text(item.get("body") or item.get("description"), limit=MAX_SNIPPET_CHARS)

        if not url or (not title and not snippet):
            continue
        if url in seen_urls:
            continue

        seen_urls.add(url)
        results.append(SearchResult(title=title, url=url, snippet=snippet))

        if len(results) >= limit:
            break

    return results
