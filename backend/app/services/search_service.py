from __future__ import annotations

import html as _html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from urllib.parse import urlparse

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
_AUTHORITY_TITLE_WORDS_RE = re.compile(r"官方|热线|中心|医院|卫健委|教育部|研究所|学会|协会|政府|公益|卫生|疾控|精神卫生")

# --- Domain authority scoring ---

# Tier 1: government, institutional, academic — highest trust
_TIER1_DOMAINS = frozenset({
    # Chinese government
    "gov.cn",
    # Health authorities
    "who.int", "nih.gov", "nhs.uk", "cdc.gov",
    # Chinese academic
    "edu.cn",
    # Psychiatric / psychological professional orgs
    "psych.ac.cn", "cma.org.cn", "cpma.org.cn",
})

# Tier 2: authoritative content platforms, major hospitals, professional portals
_TIER2_GLOB = (
    "baike.baidu.com",
    "zh.wikipedia.org",
    "yiyuan.health",
    "jk.cn",
    "medlive.cn",
    "dxy.cn",
)
_TIER2_SUFFIX = (
    ".hospital.",
    ".yy.",
    ".med.",
    ".psy.",
)


def _score_domain(url: str) -> int:
    """Score a URL by domain trust tier. Higher = more authoritative."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return 0

    if not hostname:
        return 0

    hostname_lower = hostname.lower()

    # Tier 1 exact match or suffix
    if hostname_lower in _TIER1_DOMAINS or hostname_lower.endswith(".gov.cn") or hostname_lower.endswith(".edu.cn"):
        if hostname_lower in _TIER1_DOMAINS or any(
            hostname_lower.endswith(suffix)
            for suffix in (".nhc.gov.cn", ".cdc.gov.cn", ".moe.gov.cn", ".cas.cn", ".ac.cn")
        ):
            return 100
        return 100

    # Tier 2 glob match
    for glob in _TIER2_GLOB:
        if glob in hostname_lower:
            return 50
    for suffix in _TIER2_SUFFIX:
        if suffix in hostname_lower:
            return 50

    return 0


def _score_https(url: str) -> int:
    return 5 if url.startswith("https://") else 0


def _score_path_shallow(url: str) -> int:
    """Prefer URLs with ≤2 path segments (closer to root = more likely official page)."""
    try:
        path = urlparse(url).path or ""
    except Exception:
        return 0
    segments = [s for s in path.strip("/").split("/") if s]
    return 5 if len(segments) <= 2 else 0


def _score_title_authority(title: str) -> int:
    """Title containing authority keywords (医院, 官方, 热线, etc.) gets bonus."""
    return 10 if _AUTHORITY_TITLE_WORDS_RE.search(title) else 0


# --- Cleaning helpers ---

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
    window = text[:max_chars + 1]
    matches = list(_TRUNCATION_BOUNDARY_RE.finditer(window))
    for m in reversed(matches):
        candidate = text[: m.end()].rstrip()
        if len(candidate) <= max_chars and candidate:
            if not candidate[-1].isalnum() or m.group() in {"\n", "\u3002"}:
                return candidate
    return text[:max_chars].rstrip()


# --- Dedup helpers ---

def _dedup_key(snippet: str) -> str:
    """Normalize the first N chars of a snippet for fuzzy dedup."""
    chunk = snippet[:_DEDUP_SNIPPET_PREFIX].lower()
    return _DEDUP_RE.sub("", chunk)


def _ngram_fingerprint(text: str) -> tuple[str, int, frozenset[str] | None]:
    """Return (dedup_key, length, 5-grams) for a deduplicated snippet prefix.

    Pre-computed once per result, then compared cheaply via fingerprint_match().
    """
    key = _dedup_key(text)
    if len(key) < 10:
        return key, len(key), None
    ngrams = frozenset(key[i : i + 5] for i in range(len(key) - 4))
    return key, len(key), ngrams


def _fingerprints_match(fp_a: tuple[str, int, frozenset[str] | None], fp_b: tuple[str, int, frozenset[str] | None]) -> bool:
    """Check if two pre-computed fingerprints indicate duplicate snippets."""
    key_a, len_a, ngrams_a = fp_a
    key_b, len_b, ngrams_b = fp_b
    if len_a < 10 or len_b < 10:
        return key_a == key_b
    if key_a == key_b:
        return True
    assert ngrams_a is not None and ngrams_b is not None
    overlap = len(ngrams_a & ngrams_b) / len(ngrams_a)
    return overlap >= 0.7


# --- Data types ---

@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    score: int = 0


# --- Search ---

def _ddg_text(query: str, *, region: str, max_results: int) -> list[dict[str, object]]:
    """Thin wrapper over DDGS for testability via patching."""
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, region=region, max_results=max_results))
    return [dict(item) for item in raw if isinstance(item, dict)]


def _compute_score(url: str, title: str) -> int:
    return _score_domain(url) + _score_https(url) + _score_path_shallow(url) + _score_title_authority(title)


def search_web(query: str, *, max_results: int = DEFAULT_MAX_RESULTS, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> list[SearchResult]:
    """Search DuckDuckGo for the given query, returning cleaned, deduplicated results ranked by authority.

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

    candidates: list[SearchResult] = []
    seen_urls: set[str] = set()
    seen_fingerprints: list[tuple[str, int, frozenset[str] | None]] = []

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

        fp = _ngram_fingerprint(snippet)
        if any(_fingerprints_match(fp, prev) for prev in seen_fingerprints):
            continue

        seen_urls.add(url)
        seen_fingerprints.append(fp)

        score = _compute_score(url, title)
        candidates.append(SearchResult(title=title, url=url, snippet=snippet, score=score))

    # Sort by score descending (higher authority first), then take top-N
    candidates.sort(key=lambda r: r.score, reverse=True)
    return candidates[:limit]
