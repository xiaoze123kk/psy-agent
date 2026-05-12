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
