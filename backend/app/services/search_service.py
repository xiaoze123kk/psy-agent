from __future__ import annotations

import html as _html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass

from duckduckgo_search import DDGS

from app.services.tooling import _clean_text, _clamp_int


logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 3
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_SNIPPET_CHARS = 280
SEARCH_REGION = "cn"
_DEDUP_SNIPPET_PREFIX = 60
_ELLIPSIS_RE = re.compile(r"^\.{2,}|\.{2,}$")
_TRUNCATION_BOUNDARY_RE = re.compile(r"[。，、；：？！\u3000\s,.;:!?\n]")
_DEDUP_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


def _strip_ellipsis(text: str) -> str:
    return _ELLIPSIS_RE.sub("", text).strip()


def _unescape_html(text: str) -> str:
    return _html.unescape(text)


def _clean(content: str, limit: int) -> str:
    return _strip_ellipsis(_unescape_html(_clean_text(content, limit=limit)))


def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, preferring CJK punctuation or whitespace boundaries."""
    if len(text) <= max_chars:
        return text
    # Find the last boundary in the max_chars window
    window = text[:max_chars + 1]
    matches = list(_TRUNCATION_BOUNDARY_RE.finditer(window))
    for m in reversed(matches):
        candidate = text[: m.end()].rstrip()
        if len(candidate) <= max_chars and candidate:
            # Ensure we don't end on an alphanumeric mid-word
            if not candidate[-1].isalnum() or m.group() in {"\n", "\u3002"}:
                return candidate
    # Fallback: hard truncate at max_chars and strip
    return text[:max_chars].rstrip()


def _dedup_key(snippet: str) -> str:
    """Normalize the first N chars of a snippet for fuzzy dedup."""
    chunk = snippet[:_DEDUP_SNIPPET_PREFIX].lower()
    return _DEDUP_RE.sub("", chunk)


def _is_similar_snippet(a: str, b: str) -> bool:
    """Check if two snippets are similar enough to be considered duplicates.

    Uses overlapping 5-gram character sets within the first 60 chars of each snippet.
    """
    short = _dedup_key(a)
    other = _dedup_key(b)
    if len(short) < 10 or len(other) < 10:
        return short == other
    if short == other:
        return True
    short_ngrams = {short[i : i + 5] for i in range(len(short) - 4)}
    other_ngrams = {other[i : i + 5] for i in range(len(other) - 4)}
    if not short_ngrams:
        return False
    overlap = len(short_ngrams & other_ngrams) / len(short_ngrams)
    return overlap >= 0.7


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


def search_web(query: str, *, max_results: int = DEFAULT_MAX_RESULTS, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> list[SearchResult]:
    """Search DuckDuckGo for the given query, returning cleaned, deduplicated results.

    Returns an empty list on any error (network, timeout, parse, etc.).
    """
    cleaned_query = _clean_text(query, limit=240)
    if not cleaned_query:
        return []

    limit = _clamp_int(max_results, default=DEFAULT_MAX_RESULTS, minimum=1, maximum=5)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_ddg_text, cleaned_query, region=SEARCH_REGION, max_results=limit * 3)
            raw_items = future.result(timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("DuckDuckGo search timed out after %.1fs for query: %s", timeout_seconds, cleaned_query[:80])
        return []
    except Exception:
        logger.warning("DuckDuckGo search failed for query: %s", cleaned_query[:80])
        return []

    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    seen_snippets: list[str] = []  # Previous snippets for similarity check

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        title = _clean(item.get("title") or "", limit=120)
        url = _clean_text(item.get("href") or item.get("url"), limit=500)
        snippet = _clean(item.get("body") or item.get("description") or "", limit=600)
        if snippet:
            snippet = _smart_truncate(snippet, MAX_SNIPPET_CHARS)

        if not url or (not title and not snippet):
            continue

        if url in seen_urls:
            continue

        # Check snippet similarity against already-accepted results
        if any(_is_similar_snippet(snippet, prev) for prev in seen_snippets):
            continue

        seen_urls.add(url)
        seen_snippets.append(snippet)
        results.append(SearchResult(title=title, url=url, snippet=snippet))

        if len(results) >= limit:
            break

    return results
