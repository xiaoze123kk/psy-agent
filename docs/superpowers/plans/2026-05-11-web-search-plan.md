# Web Search Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `web_search` tool to the existing tooling framework so the LLM can search DuckDuckGo for real-time psychological support resources (hotlines, institutions) and authoritative information.

**Architecture:** One new service file (`search_service.py`) wraps DuckDuckGo text search, one new ToolSpec in `tooling.py` registers the tool with a handler. ToolGate treats it like `search_memories` (allowed at L0/L1, blocked at L2/L3). Fully TDD.

**Tech Stack:** `duckduckgo_search` library (MIT license, no API key), existing `httpx`, Python 3.11+

---

### Task 1: Add duckduckgo_search dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add duckduckgo_search to requirements.txt**

```diff
 sqlalchemy>=2.0.36,<3.0.0
 psycopg[binary]>=3.2.3,<4.0.0
 httpx>=0.27.0,<1.0.0
+duckduckgo_search>=6.0,<8.0
 pymilvus>=2.5.0,<3.0.0
```

- [ ] **Step 2: Install the dependency**

Run: `cd backend && pip install "duckduckgo_search>=6.0,<8.0"`

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add duckduckgo_search dependency for web search tool"
```

---

### Task 2: Write failing tests for search_service

**Files:**
- Create: `backend/tests/test_search_service.py`

- [ ] **Step 1: Write the test file**

```python
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.search_service import SearchResult, search_web


_SEARCH_RESULT_MISSING_URL = {
    "title": "Missing URL",
    "href": "",
    "body": "This result has no URL and should be filtered out.",
}
_SEARCH_RESULT_FULL = {
    "title": "  心理援助热线  ",
    "href": "https://example.com/hotline",
    "body": "  全国心理援助热线：400-161-9995。提供 24 小时免费心理咨询。  ",
}
_SEARCH_RESULT_NEARLY_EMPTY = {
    "title": "",
    "href": "https://empty.example.com",
    "body": "",
}


class SearchServiceTests(unittest.TestCase):
    def test_search_web_returns_cleaned_results(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_MISSING_URL, _SEARCH_RESULT_FULL],
        ):
            results = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertIsInstance(item, SearchResult)
        self.assertEqual(item.title, "心理援助热线")
        self.assertEqual(item.url, "https://example.com/hotline")
        self.assertIn("400-161-9995", item.snippet)

    def test_search_web_empty_query_returns_empty(self) -> None:
        with patch("app.services.search_service._ddg_text", return_value=[]):
            results = search_web("   ", max_results=3)

        self.assertEqual(results, [])

    def test_search_web_filters_empty_titles_and_snippets(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_NEARLY_EMPTY, _SEARCH_RESULT_FULL],
        ):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理援助热线")

    def test_search_web_respects_max_results(self) -> None:
        raw_results = []
        for i in range(8):
            raw_results.append({
                "title": f"Result {i}",
                "href": f"https://example.com/{i}",
                "body": f"Body {i}",
            })

        with patch("app.services.search_service._ddg_text", return_value=raw_results):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 3)

    def test_search_web_snippet_truncation(self) -> None:
        long_body = "x" * 600
        raw = [{"title": "T", "href": "https://x.com", "body": long_body}]

        with patch("app.services.search_service._ddg_text", return_value=raw):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertLessEqual(len(results[0].snippet), 300)

    def test_search_web_network_error_returns_empty(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            side_effect=Exception("network timeout"),
        ):
            results = search_web("crisis hotline", max_results=3)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_search_service.py -v`

Expected: All 6 tests fail with `ModuleNotFoundError: No module named 'app.services.search_service'`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_search_service.py
git commit -m "test: add failing tests for search_service"
```

---

### Task 3: Implement search_service.py

**Files:**
- Create: `backend/app/services/search_service.py`

- [ ] **Step 1: Write the minimal implementation**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from duckduckgo_search import DDGS

from app.services.tooling import _clean_text, _clamp_int, _safe_preview


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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_search_service.py -v`

Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/search_service.py
git commit -m "feat: add search_service with DuckDuckGo web search"
```

---

### Task 4: Write failing tests for web_search in tooling

**Files:**
- Modify: `backend/tests/test_tooling.py`

- [ ] **Step 1: Add test class for web_search tool gate and handler behavior**

Add these imports at the top of the file (after existing imports):

```python
from unittest.mock import patch

from app.services.tooling import LOW_RISK_LEVELS, TOOL_SPEC_BY_NAME, ToolGate, build_dialogue_tool_plan, summarize_tool_events
```

Note: `ToolGate`, `build_dialogue_tool_plan`, and `summarize_tool_events` are already imported. Add `LOW_RISK_LEVELS` and `TOOL_SPEC_BY_NAME` to the existing import, and add `patch` to `unittest.mock`.

Add the new test class at the end of the file, before `if __name__ == "__main__":`:

```python
class WebSearchToolTests(unittest.TestCase):
    def test_web_search_spec_is_registered(self) -> None:
        spec = TOOL_SPEC_BY_NAME.get("web_search")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "web_search")
        self.assertEqual(spec.enabled_by_default, True)
        self.assertEqual(spec.allowed_risk_levels, LOW_RISK_LEVELS)
        tool_def = spec.to_deepseek_tool()
        self.assertEqual(tool_def["function"]["name"], "web_search")
        self.assertIn("query", tool_def["function"]["parameters"]["properties"])

    def test_web_search_appears_in_low_risk_plan(self) -> None:
        plan = build_dialogue_tool_plan(make_state())
        tool_names = [tool["function"]["name"] for tool in plan.tools]

        self.assertIn("web_search", tool_names)
        self.assertIn("web_search", plan.allowed_tool_names)
        self.assertNotIn("web_search", plan.blocked_tool_names)

    def test_web_search_blocked_at_high_risk(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        tool_names = [tool["function"]["name"] for tool in plan.tools]
        self.assertNotIn("web_search", tool_names)
        self.assertIn("web_search", plan.blocked_tool_names)

    @staticmethod
    def _search_result(title: str, url: str, snippet: str) -> dict[str, object]:
        return {"title": title, "href": url, "body": snippet}

    def test_web_search_handler_returns_search_results(self) -> None:
        from app.services.search_service import SearchResult

        mock_results = [
            SearchResult(
                title="北京心理援助热线",
                url="https://example.com/beijing",
                snippet="北京市心理援助热线：010-82951332",
            ),
        ]

        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch(
            "app.services.tooling.search_web",
            return_value=mock_results,
        ):
            result = plan.tool_handlers["web_search"]({"query": "北京心理援助热线"})

        self.assertEqual(result["query"], "北京心理援助热线")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["title"], "北京心理援助热线")
        self.assertEqual(item["url"], "https://example.com/beijing")
        self.assertIn("010-82951332", item["snippet"])

    def test_web_search_handler_empty_query(self) -> None:
        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.tooling.search_web", return_value=[]):
            result = plan.tool_handlers["web_search"]({"query": "", "max_results": 3})

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])

    def test_web_search_handler_records_preview(self) -> None:
        from app.services.search_service import SearchResult

        mock_results = [
            SearchResult(
                title="Hotline",
                url="https://example.com/hotline",
                snippet="A helpful resource.",
            ),
        ]

        state = make_state()
        plan = build_dialogue_tool_plan(state)

        with patch("app.services.tooling.search_web", return_value=mock_results):
            plan.tool_handlers["web_search"]({"query": "help"})

        previews = plan.audit_capture.previews
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["name"], "web_search")
        self.assertEqual(previews[0]["status"], "completed")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_tooling.py::WebSearchToolTests -v`

Expected: `test_web_search_spec_is_registered` fails with `AssertionError: None != 'web_search'` because `web_search` is not yet in `TOOL_SPEC_BY_NAME`. Other tests fail similarly.

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd backend && python -m pytest tests/test_tooling.py::ToolGateTests tests/test_tooling.py::MemoryToolHandlerTests tests/test_tooling.py::ToolAuditSummaryTests -v`

Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_tooling.py
git commit -m "test: add failing tests for web_search tool integration"
```

---

### Task 5: Implement web_search tool in tooling.py

**Files:**
- Modify: `backend/app/services/tooling.py`

- [ ] **Step 1: Add web_search ToolSpec to TOOL_SPECS tuple**

Add to the import section (after `from app.services.safety_service import build_safety_resources`):

```python
from app.services.search_service import search_web
```

Add the new ToolSpec at the end of `TOOL_SPECS` tuple, after `ask_knowledge` and before the closing `)`:

```python
    ToolSpec(
        name="web_search",
        description="Search the web for real-time information about psychological support resources, hotlines, and professional mental health information.",
        allowed_risk_levels=LOW_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords for finding psychological support resources or professional health information.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Maximum number of results to return (1-5).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
```

- [ ] **Step 2: Add `"web_search"` to ToolGate.allows()**

In the `ToolGate.allows()` method, add `"web_search"` to the set of tools allowed at low risk levels. Change the return line:

```python
        if self.memory_mode == "off":
            return name in SAFETY_TOOL_NAMES
        return name in (MEMORY_TOOL_NAMES | SAFETY_TOOL_NAMES | ({"ask_knowledge"} if self.knowledge_enabled else set()))
```

to:

```python
        if self.memory_mode == "off":
            return name in SAFETY_TOOL_NAMES
        return name in (MEMORY_TOOL_NAMES | SAFETY_TOOL_NAMES | {"web_search"} | ({"ask_knowledge"} if self.knowledge_enabled else set()))
```

- [ ] **Step 3: Add web_search handler factory and register in build_dialogue_tool_plan()**

Add the handler factory function after `_build_get_safety_resources_handler`:

```python
def _build_web_search_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def web_search_tool(arguments: dict[str, Any]) -> dict[str, Any]:
        query = _clean_text(arguments.get("query"), limit=240)
        max_results = _clamp_int(arguments.get("max_results"), default=3, minimum=1, maximum=5)
        results = search_web(query, max_results=max_results)
        items: list[dict[str, Any]] = []
        for result in results:
            items.append({
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
            })
        capture.record_preview(
            "web_search",
            status="completed",
            preview=[
                {"title": result.title, "url": result.url}
                for result in results[:3]
            ],
        )
        return {
            "query": query,
            "count": len(items),
            "items": items,
        }

    return web_search_tool
```

In `build_dialogue_tool_plan()`, after the `get_safety_resources` handler registration block:

```python
    if "get_safety_resources" in allowed_names:
        handlers["get_safety_resources"] = _build_get_safety_resources_handler(state, capture)
```

Add:

```python
    if "web_search" in allowed_names:
        handlers["web_search"] = _build_web_search_handler(state, capture)
```

- [ ] **Step 4: Add web_search to the tool prompt hint**

In `_tool_prompt_hint()`, add to the `descriptions` dict:

```python
        "web_search": "web_search: search the web for real-time psychological support resources; return title, url, and snippet.",
```

- [ ] **Step 5: Run all tooling tests**

Run: `cd backend && python -m pytest tests/test_tooling.py -v`

Expected: All tests PASS (both existing and new WebSearchToolTests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tooling.py
git commit -m "feat: add web_search tool for real-time psychological resource search"
```

---

### Task 6: Run full test suite and verify

**Files:**
- (none modified, verification only)

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests PASS, no regressions

- [ ] **Step 2: Do a quick manual smoke test**

```bash
cd backend && python -c "from app.services.search_service import search_web; results = search_web('全国心理援助热线', max_results=2); print(results)"
```

Expected: Prints 1-2 SearchResult objects with real titles/URLs from DuckDuckGo

- [ ] **Step 3: Commit (if any test fixes were needed)**

```bash
git add -A
git commit -m "test: verify web_search integration passes full test suite"
```

---

### Task 7: Update tool prompting for web_search

**Files:**
- Modify: `backend/app/services/tooling.py`

- [ ] **Step 1: Update _tool_prompt_hint to include web_search guidance**

In `_tool_prompt_hint()`, the `descriptions` dict already has an entry from Task 5. Extend the `[Tool policy]` block's guidance lines. After the existing line:

```python
    lines.extend(f"- {descriptions[name]}" for name in tool_names if name in descriptions)
```

Add:

```python
    if "web_search" in tool_names:
        lines.append("- web_search: Only search for psychological support resources or professional mental health information. Do NOT include any user personal information in the search query.")
```

- [ ] **Step 2: Run tests to verify no regression**

Run: `cd backend && python -m pytest tests/test_tooling.py -v`

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/tooling.py
git commit -m "feat: add web_search prompt guidance to prevent PII in queries"
```
