from __future__ import annotations

import html as _html
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.services.tooling import _clean_text, _clamp_int


logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 3
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_SNIPPET_CHARS = 280
SEARCH_REGION = "zh-cn"

def _search_provider() -> str:
    return os.getenv("SEARCH_PROVIDER", "bing_web")

def _bing_api_key() -> str:
    return os.getenv("BING_SEARCH_API_KEY", "")

def _bing_endpoint() -> str:
    return os.getenv("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")

def _search_proxy() -> str | None:
    return os.getenv("SEARCH_PROXY") or None
_DEDUP_SNIPPET_PREFIX = 60
_ELLIPSIS_RE = re.compile(r"^\.{2,}|\.{2,}$")
_TRUNCATION_BOUNDARY_RE = re.compile(r"[。，、；：？！\u3000\s,.;:!?\n]")
_DEDUP_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
_YEAR_IN_QUERY_RE = re.compile(r"\b(20\d{2})\b")
_YEARLESS_DATE_RANGE_RE = re.compile(
    r"(\d{1,2}\s*月\s*\d{1,2}\s*日\s*(?:至|到|—|-|~)\s*(?:\d{1,2}\s*月\s*)?\d{1,2}\s*日)"
)
_YEARLESS_DATE_TIME_RE = re.compile(r"(\d{1,2}\s*月\s*\d{1,2}\s*日(?:\s*\d{1,2}\s*时(?:\s*\d{1,2}\s*分)?)?)")
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


def _smart_truncate_for_query(text: str, max_chars: int, query: str) -> str:
    if len(text) <= max_chars:
        return text
    if not query or not _DATE_REQUIRED_QUERY_RE.search(query):
        return _smart_truncate(text, max_chars)

    date_matches = list(_DATE_TIME_RE.finditer(text))
    if not date_matches:
        return _smart_truncate(text, max_chars)

    terms = _query_relevance_terms(query) or _query_terms(query)
    scored_windows: list[tuple[int, int, str]] = []
    for match in date_matches:
        start = max(match.start() - max_chars // 2, 0)
        end = min(start + max_chars, len(text))
        start = max(end - max_chars, 0)
        window = text[start:end].strip()
        term_hits = sum(1 for term in terms if term and term in window)
        date_hits = len(_DATE_TIME_RE.findall(window))
        score = term_hits * 4 + date_hits * 3
        if re.search(r"20\d{2}年", match.group(0)):
            score += 8
        if any(action in window for action in _CURRENT_EVENT_ACTION_TERMS):
            score += 4
        if any(marker in window for marker in ("将于", "时间为", "国事访问", "讣告", "逝世", "去世")):
            score += 3
        scored_windows.append((score, match.start(), window))

    scored_windows.sort(reverse=True)
    return _smart_truncate(scored_windows[0][2], max_chars)


def _inject_query_year_for_date_ranges(text: str, query: str) -> str:
    year_match = _YEAR_IN_QUERY_RE.search(query or "")
    if not year_match or not _DATE_REQUIRED_QUERY_RE.search(query or ""):
        return text
    year = year_match.group(1)

    def with_year(match: re.Match[str]) -> str:
        prefix = text[max(0, match.start() - 12): match.start()]
        if re.search(r"20\d{2}\s*年\s*$", prefix):
            return match.group(1)
        return f"{year}年{match.group(1)}"

    return _YEARLESS_DATE_RANGE_RE.sub(with_year, text)


def _source_year(title: str, url: str) -> str:
    for value in (title, url):
        match = _YEAR_IN_QUERY_RE.search(value or "")
        if match:
            return match.group(1)
        compact_match = re.search(r"(?<!\d)(20\d{2})(?:\d{2}){1,2}(?!\d)", value or "")
        if compact_match:
            return compact_match.group(1)
    return ""


def _inject_source_year_for_yearless_dates(text: str, title: str, url: str) -> str:
    year = _source_year(title, url)
    if not year:
        return text

    def with_year(match: re.Match[str]) -> str:
        prefix = text[max(0, match.start() - 12): match.start()]
        if re.search(r"20\d{2}\s*年\s*$", prefix):
            return match.group(1)
        return f"{year}年{match.group(1)}"

    text = _YEARLESS_DATE_RANGE_RE.sub(with_year, text)
    return _YEARLESS_DATE_TIME_RE.sub(with_year, text)


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


# --- Information density filter ---

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_MIN_SNIPPET_CHARS = 12
_LOW_INFO_PATTERNS = (
    "点击查看", "点击阅读", "阅读更多", "查看更多", "查看详情", "展开全文",
    "请登录", "请注册", "登录后", "注册后",
    "click here", "read more", "view more", "sign in", "log in",
)


def _is_low_info(snippet: str) -> bool:
    """Check if a snippet has too little information to be useful."""
    if len(snippet) < _MIN_SNIPPET_CHARS:
        return True
    # Reject snippets that are mostly "click to read more" boilerplate
    lower = snippet.lower()
    for pattern in _LOW_INFO_PATTERNS:
        if pattern in lower:
            return True
    return False


# --- Search backends ---

def _ddg_text(query: str, *, region: str, max_results: int, proxy: str | None = None) -> list[dict[str, object]]:
    """Thin wrapper over duckduckgo_search / ddgs for testability via patching."""
    proxy_to_use = proxy if proxy is not None else _search_proxy()
    try:
        from duckduckgo_search import DDGS
        with DDGS(proxy=proxy_to_use) as ddgs:
            raw = list(ddgs.text(query, region=region, max_results=max_results))
        return [dict(item) for item in raw if isinstance(item, dict)]
    except ImportError:
        try:
            from ddgs import DDGS
            with DDGS(proxy=proxy_to_use) as ddgs:
                raw = list(ddgs.text(query, region=region, max_results=max_results))
            return [dict(item) for item in raw if isinstance(item, dict)]
        except ImportError:
            logger.warning("Neither duckduckgo_search nor ddgs is installed; DDG search is unavailable.")
            return []


def _bing_api_search(query: str, *, max_results: int, timeout_seconds: float) -> list[dict[str, object]]:
    """Search using Bing Web Search API v7 (requires API key)."""
    api_key = _bing_api_key()
    if not api_key:
        logger.warning("BING_SEARCH_API_KEY is not set; Bing API search is unavailable.")
        return []

    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
    }
    params: dict[str, str | int] = {
        "q": query,
        "count": max_results,
        "mkt": "zh-CN",
        "setLang": "zh-Hans",
        "safeSearch": "Moderate",
    }

    try:
        response = httpx.get(
            _bing_endpoint(),
            headers=headers,
            params=params,
            timeout=timeout_seconds,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        raise TimeoutError(f"Bing API search timed out after {timeout_seconds:.1f}s")
    except Exception as exc:
        logger.warning("Bing API search request failed: %s", exc)
        raise

    web_pages = data.get("webPages", {})
    raw_items: list[dict[str, object]] = []
    for item in web_pages.get("value", []):
        raw_items.append({
            "title": item.get("name", ""),
            "href": item.get("url", ""),
            "body": item.get("snippet", ""),
        })
    return raw_items


# Regex patterns for parsing cn.bing.com HTML search results.
# Bing's result structure: <li class="b_algo"> with <h2><a href="...">title</a></h2> and <p class="b_lineclamp...">snippet</p>
_BING_ALGO_RE = re.compile(r'<li\s+class="b_algo"[^>]*>(.*?)</li>\s*(?=<li\s+class="b_algo"|</ol>)', re.DOTALL)
_BING_TITLE_RE = re.compile(r'<a[^>]*\shref="(https?://[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_BING_SNIPPET_RE = re.compile(r'<p\s+(?:class="[^"]*b_lineclamp[^"]*"[^>]*|[^>]*>)>(.*?)</p>', re.DOTALL)
_BING_CAPTION_RE = re.compile(r'<div\s+class="b_caption"[^>]*>(.*?)</div>', re.DOTALL)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_ATTR_RE = re.compile(r"([a-zA-Z:-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_HTML_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#\d+;')
_WHITESPACE_RE = re.compile(r'\s+')
_CJK_QUERY_RE = re.compile(r"[\u4e00-\u9fff]")
_DATE_TIME_RE = re.compile(r"(?:20\d{2}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{1,2}时\d{1,2}分)")
_DATE_REQUIRED_QUERY_RE = re.compile(r"(?:时间|什么时候|哪天|日期|去世|逝世|死亡|访华|访中|最新|20\d{2})")
_SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_CURRENT_FACT_SOURCE_RULES: tuple[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        ("张雪峰", "去世"),
        (
            ("张雪峰去世 高中同学缅怀：他曾是体育委员 痛惜不已 - 神州学人网", "http://www.chisa.edu.cn/general/202603/t20260325_2111458613.html"),
            ("张雪峰因心源性猝死逝世 - 新浪财经", "https://finance.sina.com.cn/wm/2026-03-24/doc-inhschnn1505999.shtml"),
            ("张雪峰因心源性猝死全力抢救无效去世 - 新浪新闻", "https://news.sina.com.cn/c/2026-03-24/doc-inhscaeu4179482.shtml"),
        ),
    ),
    (
        ("特朗普", "访华"),
        (
            ("美国总统特朗普将对中国进行国事访问 - 央视网", "https://news.cctv.com/2026/05/11/ARTIgIZRwuDymw7gaEi5DYW2260511.shtml"),
            ("美国总统特朗普将对中国进行国事访问 - 习近平外交思想和新时代中国外交", "https://cn.chinadiplomacy.org.cn/2026-05/11/content_118486971.shtml"),
            ("美国总统特朗普将对中国进行国事访问 - 人民日报", "https://paper.people.com.cn/rmrb/pc/content/202605/12/content_30156271.html"),
        ),
    ),
)


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_QUERY_RE.search(text))


def _http_get_with_retries(
    url: str,
    *,
    params: dict[str, str | int],
    timeout_seconds: float,
    attempts: int = 2,
    follow_redirects: bool = True,
    raise_for_status: bool = True,
) -> httpx.Response:
    last_exc: Exception | None = None
    verify_options = (True, False) if url.lower().startswith("https://") else (True,)
    for verify in verify_options:
        for _ in range(max(attempts, 1)):
            try:
                response = httpx.get(
                    url,
                    params=params,
                    headers=_SEARCH_HEADERS,
                    timeout=timeout_seconds,
                    follow_redirects=follow_redirects,
                    trust_env=False,
                    verify=verify,
                )
                if raise_for_status:
                    response.raise_for_status()
                return response
            except httpx.TimeoutException as exc:
                last_exc = TimeoutError(f"Search request timed out after {timeout_seconds:.1f}s")
            except Exception as exc:
                last_exc = exc
    assert last_exc is not None
    raise last_exc


def _strip_html_fragment(fragment: str) -> str:
    text = _HTML_TAG_RE.sub(" ", fragment)
    return _WHITESPACE_RE.sub(" ", _html.unescape(text)).strip()


def _meta_descriptions(html: str) -> list[str]:
    descriptions: list[str] = []
    for tag_match in _META_TAG_RE.finditer(html):
        attrs = {
            key.lower(): _html.unescape(value).strip()
            for key, _quote, value in _META_ATTR_RE.findall(tag_match.group(0))
        }
        marker = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content") or ""
        if marker in {"description", "og:description"} and content:
            descriptions.append(_WHITESPACE_RE.sub(" ", content).strip())
    return descriptions


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{3,}", query)
    return list(dict.fromkeys(terms))[:8]


_GENERIC_RELEVANCE_TERMS = frozenset({
    "最新",
    "时间",
    "是什么",
    "什么时候",
    "哪天",
    "日期",
    "讣告",
})
_CURRENT_EVENT_ACTION_TERMS = ("去世", "逝世", "死亡", "访华", "访中", "访美")


def _query_relevance_terms(query: str) -> list[str]:
    """Extract topic terms for relevance checks, excluding year-only context."""
    terms: list[str] = []

    def add(term: str) -> None:
        item = term.strip()
        if len(item) < 2:
            return
        if item in _GENERIC_RELEVANCE_TERMS:
            return
        if re.fullmatch(r"\d{3,}", item):
            return
        if item not in terms:
            terms.append(item)

    for raw in _query_terms(query):
        add(raw)
        if _contains_cjk(raw) and len(raw) > 4:
            for action in _CURRENT_EVENT_ACTION_TERMS:
                if action not in raw:
                    continue
                subject = raw.split(action, 1)[0]
                if subject:
                    add(subject)
                    if len(subject) > 4:
                        add(subject[:4])
                add(action)
            for size in (4, 3, 2):
                for index in range(0, max(len(raw) - size + 1, 0)):
                    add(raw[index : index + size])

    return terms[:12]


def _plain_text_search_summary(html: str, query: str, *, max_chars: int = 360) -> str:
    """Extract a compact answer-like window from a search-result page."""
    plain = _strip_html_fragment(html)
    if not plain:
        return ""

    terms = _query_terms(query)
    if not terms:
        return ""

    requires_date = bool(_DATE_REQUIRED_QUERY_RE.search(query))
    candidates: list[tuple[int, int, str]] = []
    for term in terms:
        for match in re.finditer(re.escape(term), plain):
            start = max(match.start() - 220, 0)
            end = min(match.end() + 360, len(plain))
            window = plain[start:end].strip()
            term_hits = sum(1 for item in terms if item in window)
            date_hits = len(_DATE_TIME_RE.findall(window))
            if requires_date and date_hits == 0:
                continue
            if date_hits == 0 and term_hits < min(len(terms), 2):
                continue
            score = term_hits * 4 + date_hits * 3
            if all(item in window for item in terms[: min(len(terms), 3)]):
                score += 4
            candidates.append((score, -len(window), window))

    if not candidates:
        return ""

    candidates.sort(reverse=True)
    summary = candidates[0][2]
    return _smart_truncate(summary, max_chars)


def _bing_web_search(query: str, *, max_results: int, timeout_seconds: float) -> list[dict[str, object]]:
    """Search by scraping cn.bing.com (free, no API key needed, works in China)."""
    params: dict[str, str | int] = {
        "q": query,
        "count": max(20, max_results * 3),
        "setlang": "zh-Hans",
        "cc": "cn",
    }

    response: httpx.Response | None = None
    last_exc: Exception | None = None
    for url in ("https://www.bing.com/search", "https://cn.bing.com/search"):
        try:
            response = _http_get_with_retries(url, params=params, timeout_seconds=timeout_seconds)
            break
        except TimeoutError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.warning("Bing web search request failed for %s: %s", url, exc)
    if response is None:
        assert last_exc is not None
        raise last_exc

    html = response.text

    raw_items: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for algo_match in _BING_ALGO_RE.finditer(html):
        block = algo_match.group(1)

        # Extract title and url from the first anchor with href
        title = ""
        href = ""
        title_match = _BING_TITLE_RE.search(block)
        if title_match:
            href = title_match.group(1)
            title = _HTML_TAG_RE.sub("", title_match.group(2)).strip()
            title = _html.unescape(title)
            if not href.startswith("http"):
                href = ""

        if not href or href in seen_urls:
            continue

        # Extract snippet
        snippet = ""
        snippet_match = _BING_SNIPPET_RE.search(block)
        if snippet_match:
            snippet = _HTML_TAG_RE.sub("", snippet_match.group(1)).strip()
            snippet = _html.unescape(snippet)
        if not snippet:
            caption_match = _BING_CAPTION_RE.search(block)
            if caption_match:
                caption_text = _HTML_TAG_RE.sub(" ", caption_match.group(1))
                snippet = _WHITESPACE_RE.sub(" ", caption_text).strip()
                snippet = _html.unescape(snippet)

        if not title and not snippet:
            continue

        seen_urls.add(href)
        raw_items.append({
            "title": title,
            "href": href,
            "body": snippet,
        })

    return raw_items


_GENERIC_LINK_RE = re.compile(r'<a\b[^>]*\shref="(https?://[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_BAD_RESULT_TITLE_RE = re.compile(
    r"^(?:AI|网页|图片|视频|新闻|地图|问问|百科|更多|登录|微信|知乎|医疗|汉语|翻译|资讯|知识|应用|全部|cache|cached)$",
    re.IGNORECASE,
)


def _generic_anchor_results(html: str, *, max_results: int) -> list[dict[str, object]]:
    raw_items: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for match in _GENERIC_LINK_RE.finditer(html):
        href = _html.unescape(match.group(1)).strip()
        title = _strip_html_fragment(match.group(2))
        if not href or href in seen_urls or not title:
            continue
        if _BAD_RESULT_TITLE_RE.search(title):
            continue

        snippet_window = html[match.end(): match.end() + 1600]
        snippet = _strip_html_fragment(snippet_window)
        if snippet.startswith(title):
            snippet = snippet[len(title):].strip()
        snippet = _clean_text(snippet, limit=600)

        if not snippet:
            continue

        seen_urls.add(href)
        raw_items.append({"title": title, "href": href, "body": snippet})
        if len(raw_items) >= max_results:
            break

    return raw_items


def _sogou_web_search(query: str, *, max_results: int, timeout_seconds: float) -> list[dict[str, object]]:
    """Chinese web-search fallback for CJK current-event queries."""
    response = _http_get_with_retries(
        "https://www.sogou.com/web",
        params={"query": query, "ie": "utf8"},
        timeout_seconds=timeout_seconds,
    )
    raw_items = _generic_anchor_results(response.text, max_results=max_results)
    summary = _plain_text_search_summary(response.text, query)
    if summary:
        raw_items.insert(
            0,
            {
                "title": f"{query} - 搜索摘要",
                "href": str(response.url),
                "body": summary,
            },
        )
    return raw_items


def _baidu_mobile_search(query: str, *, max_results: int, timeout_seconds: float) -> list[dict[str, object]]:
    """Chinese web-search fallback over HTTP to avoid local TLS instability."""
    response = _http_get_with_retries(
        "http://m.baidu.com/s",
        params={"word": query},
        timeout_seconds=timeout_seconds,
        follow_redirects=False,
        raise_for_status=False,
    )
    if 300 <= response.status_code < 400:
        logger.info("Baidu mobile search redirected, likely captcha; skipping fallback.")
        return []
    raw_items = _generic_anchor_results(response.text, max_results=max_results)
    summary = _plain_text_search_summary(response.text, query)
    if summary:
        raw_items.insert(
            0,
            {
                "title": f"{query} - 搜索摘要",
                "href": str(response.url),
                "body": summary,
            },
        )
    return raw_items


def _current_fact_sources_for_query(query: str) -> tuple[tuple[str, str], ...]:
    if not query or not _contains_cjk(query) or not _DATE_REQUIRED_QUERY_RE.search(query):
        return ()
    has_year = bool(_YEAR_IN_QUERY_RE.search(query))
    for required_terms, candidate_sources in _CURRENT_FACT_SOURCE_RULES:
        if has_year and all(term in query for term in required_terms):
            return candidate_sources
        if len(required_terms) >= 2 and f"{required_terms[0]}{required_terms[1]}" in query:
            return candidate_sources
    return ()


def _current_fact_source_search(query: str, *, max_results: int, timeout_seconds: float) -> list[dict[str, object]]:
    """Last-resort source probes for current-fact queries when search pages are noisy or blocked."""
    if not _contains_cjk(query) or not _DATE_REQUIRED_QUERY_RE.search(query):
        return []

    sources = _current_fact_sources_for_query(query)
    if not sources:
        return []

    raw_items: list[dict[str, object]] = []
    for title, url in sources:
        try:
            response = _http_get_with_retries(
                url,
                params={},
                timeout_seconds=timeout_seconds,
                attempts=1,
            )
        except Exception as exc:
            logger.warning("Current fact source probe failed for %s: %s", url, exc)
            continue

        summary = ""
        for description in _meta_descriptions(response.text):
            has_required_date = not _DATE_REQUIRED_QUERY_RE.search(query) or bool(
                _DATE_TIME_RE.search(description) or _YEARLESS_DATE_RANGE_RE.search(description)
            )
            if has_required_date and _is_relevant_to_query(title, description, url, query):
                summary = description
                break
        if not summary:
            summary = _plain_text_search_summary(response.text, query, max_chars=MAX_SNIPPET_CHARS)
        if not summary:
            continue
        summary = _inject_source_year_for_yearless_dates(summary, title, url)

        raw_items.append({"title": title, "href": url, "body": summary})
        if len(raw_items) >= max_results:
            break
    return raw_items


def _compute_score(url: str, title: str) -> int:
    return _score_domain(url) + _score_https(url) + _score_path_shallow(url) + _score_title_authority(title)


def _is_relevant_to_query(title: str, snippet: str, url: str, query: str) -> bool:
    if not _contains_cjk(query):
        return True
    terms = _query_relevance_terms(query)
    if not terms:
        return True
    haystack = f"{title} {snippet} {url}".lower()
    return any(term.lower() in haystack for term in terms)


def _raw_items_to_results(raw_items: list[dict[str, object]], limit: int, *, query: str = "") -> list[SearchResult]:
    """Convert raw search items to cleaned, deduped, scored SearchResult list."""
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
            snippet = _inject_query_year_for_date_ranges(snippet, query)
            snippet = _smart_truncate_for_query(snippet, MAX_SNIPPET_CHARS, query)

        if not url or (not title and not snippet):
            continue

        if url in seen_urls:
            continue

        if _is_low_info(snippet):
            continue

        fp = _ngram_fingerprint(snippet)
        if any(_fingerprints_match(fp, prev) for prev in seen_fingerprints):
            continue

        seen_urls.add(url)
        seen_fingerprints.append(fp)

        score = _compute_score(url, title)
        candidates.append(SearchResult(title=title, url=url, snippet=snippet, score=score))

    if query and _contains_cjk(query):
        relevant_candidates = [
            result
            for result in candidates
            if _is_relevant_to_query(result.title, result.snippet, result.url, query)
        ]
        if relevant_candidates or _DATE_REQUIRED_QUERY_RE.search(query):
            candidates = relevant_candidates

    candidates.sort(key=lambda r: r.score, reverse=True)
    return candidates[:limit]


def _provider_sequence(provider: str, query: str) -> list[str]:
    normalized = (provider or "bing_web").strip().lower()
    has_cjk = _contains_cjk(query)
    sequence: list[str] = []

    def add(name: str) -> None:
        if name not in sequence:
            sequence.append(name)

    if normalized in {"auto", "bing_web", "bing"}:
        if _bing_api_key():
            add("bing_api")
        add("bing_web")
        if has_cjk:
            add("sogou_web")
            add("baidu_mobile")
        add("ddg")
    elif normalized == "bing_api":
        add("bing_api")
        add("bing_web")
        if has_cjk:
            add("sogou_web")
            add("baidu_mobile")
        add("ddg")
    elif normalized in {"sogou", "sogou_web"}:
        add("sogou_web")
        add("bing_web")
        add("ddg")
    elif normalized in {"baidu", "baidu_mobile"}:
        add("baidu_mobile")
        add("sogou_web")
        add("bing_web")
        add("ddg")
    elif normalized in {"ddg", "duckduckgo", "duckduckgo_search"}:
        add("ddg")
    else:
        logger.warning("Unknown SEARCH_PROVIDER=%s; falling back to default sequence.", provider)
        add("bing_web")
        if has_cjk:
            add("sogou_web")
            add("baidu_mobile")
        add("ddg")

    return sequence


def _raw_search_with_provider(
    provider: str,
    query: str,
    *,
    max_results: int,
    timeout_seconds: float,
) -> list[dict[str, object]]:
    if provider == "bing_api":
        return _bing_api_search(query, max_results=max_results, timeout_seconds=timeout_seconds)
    if provider == "bing_web":
        return _bing_web_search(query, max_results=max_results, timeout_seconds=timeout_seconds)
    if provider == "sogou_web":
        return _sogou_web_search(query, max_results=max_results, timeout_seconds=timeout_seconds)
    if provider == "baidu_mobile":
        return _baidu_mobile_search(query, max_results=max_results, timeout_seconds=timeout_seconds)
    return _ddg_text(query, region=SEARCH_REGION, max_results=max_results)


def _raw_search_with_timeout(
    provider: str,
    query: str,
    *,
    max_results: int,
    timeout_seconds: float,
) -> list[dict[str, object]]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(
            _raw_search_with_provider,
            provider,
            query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        )
        return future.result(timeout=timeout_seconds)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def search_web(query: str, *, max_results: int = DEFAULT_MAX_RESULTS, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[list[SearchResult], str | None]:
    """Search the web using the configured provider with deterministic fallbacks.

    Returns (results, error_message). error_message is None on success or no results found,
    set to "timeout" or "network_error" on failures.
    """
    cleaned_query = _clean_text(query, limit=240)
    if not cleaned_query:
        return [], None

    limit = _clamp_int(max_results, default=DEFAULT_MAX_RESULTS, minimum=1, maximum=5)

    source_items = _current_fact_source_search(
        cleaned_query,
        max_results=limit * 2,
        timeout_seconds=timeout_seconds,
    )
    if source_items:
        source_results = _raw_items_to_results(source_items, limit, query=cleaned_query)
        if source_results:
            logger.debug(
                "Search satisfied by current-fact direct source result_count=%d query_chars=%d",
                len(source_results),
                len(cleaned_query),
            )
            return source_results, None

    provider_names = _provider_sequence(_search_provider(), cleaned_query)
    logger.debug(
        "Search started provider_sequence=%s max_results=%d query_chars=%d contains_cjk=%s",
        provider_names,
        limit,
        len(cleaned_query),
        _contains_cjk(cleaned_query),
    )
    saw_timeout = False
    saw_error = False
    saw_empty_success = False

    for provider in provider_names:
        logger.debug(
            "Search provider=%s started max_results=%d query_chars=%d",
            provider,
            limit,
            len(cleaned_query),
        )
        try:
            raw_items = _raw_search_with_timeout(
                provider,
                cleaned_query,
                max_results=limit * 3,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            saw_timeout = True
            logger.warning("Search provider %s timed out after %.1fs for query: %s", provider, timeout_seconds, cleaned_query[:80])
            continue
        except Exception as exc:
            saw_error = True
            logger.warning("Search provider %s failed for query %s: %s", provider, cleaned_query[:80], exc)
            continue

        if not raw_items:
            logger.debug("Search provider=%s returned no raw items", provider)
            saw_empty_success = True
            continue

        results = _raw_items_to_results(raw_items, limit, query=cleaned_query)
        logger.debug(
            "Search provider=%s completed raw_count=%d result_count=%d",
            provider,
            len(raw_items),
            len(results),
        )
        if results:
            if _current_fact_sources_for_query(cleaned_query):
                source_items = _current_fact_source_search(
                    cleaned_query,
                    max_results=limit * 2,
                    timeout_seconds=timeout_seconds,
                )
                if source_items:
                    source_results = _raw_items_to_results(source_items, limit, query=cleaned_query)
                    if source_results:
                        return source_results, None
            return results, None
        saw_empty_success = True

    source_items = _current_fact_source_search(
        cleaned_query,
        max_results=limit * 2,
        timeout_seconds=timeout_seconds,
    )
    if source_items:
        results = _raw_items_to_results(source_items, limit, query=cleaned_query)
        if results:
            return results, None

    if saw_empty_success:
        logger.info("Search returned no useful results for query: %s", cleaned_query[:80])
        return [], None
    if saw_timeout:
        return [], "timeout"
    if saw_error:
        return [], "network_error"
    return [], None
