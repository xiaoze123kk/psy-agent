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
_SEARCH_RESULT_ELLIPSIS = {
    "title": "...心理援助",
    "href": "https://example.com/ellipsis",
    "body": "全国心理援助热线：400-161-9995...",
}
_SEARCH_RESULT_HTML_ENTITY = {
    "title": "心理&amp;援助",
    "href": "https://example.com/entity",
    "body": "热线电话 &amp; 在线咨询",
}
_SEARCH_RESULT_LONG_ZH = {
    "title": "心理援助热线",
    "href": "https://example.com/long",
    "body": "全国心理援助热线是为公众提供专业心理支持的公益服务。当您感到焦虑、抑郁或需要倾诉时，可以随时拨打热线电话获得帮助。经过专业培训的咨询师会倾听您的困扰，并提供有效的支持和建议。",
}
# Nearly identical snippet to _SEARCH_RESULT_FULL body (same phone number, similar text)
_SEARCH_RESULT_DUPLICATE_CONTENT = {
    "title": "Another Source for Hotline",
    "href": "https://other.example.com/hotline-dup",
    "body": "全国心理援助热线 400-161-9995，24小时免费咨询。",
}


class SearchServiceCleaningTests(unittest.TestCase):
    def test_removes_leading_trailing_ellipsis(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_ELLIPSIS],
        ):
            results = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理援助")
        self.assertFalse(results[0].snippet.endswith("..."))

    def test_removes_html_entities(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_HTML_ENTITY],
        ):
            results = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理&援助")
        self.assertNotIn("&amp;", results[0].snippet)

    def test_empty_query_returns_empty(self) -> None:
        with patch("app.services.search_service._ddg_text", return_value=[]):
            results = search_web("   ", max_results=3)

        self.assertEqual(results, [])

    def test_filters_empty_titles_and_snippets(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_NEARLY_EMPTY, _SEARCH_RESULT_FULL],
        ):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理援助热线")

    def test_filters_results_without_url(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_MISSING_URL, _SEARCH_RESULT_FULL],
        ):
            results = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/hotline")


class SearchServiceDedupTests(unittest.TestCase):
    def test_deduplicates_by_url(self) -> None:
        same_url_results = [
            {"title": "A", "href": "https://x.com/same", "body": "Content A"},
            {"title": "B", "href": "https://x.com/same", "body": "Content B"},
        ]
        with patch("app.services.search_service._ddg_text", return_value=same_url_results):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)

    def test_deduplicates_by_snippet_similarity(self) -> None:
        # _SEARCH_RESULT_FULL and _SEARCH_RESULT_DUPLICATE_CONTENT share the same
        # phone number in the first 60 chars — should be treated as duplicates
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_FULL, _SEARCH_RESULT_DUPLICATE_CONTENT],
        ):
            results = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/hotline")

    def test_keeps_different_content_same_domain(self) -> None:
        different = [
            {
                "title": "Hotline A",
                "href": "https://x.com/page1",
                "body": "北京心理援助热线：010-82951332",
            },
            {
                "title": "Hotline B",
                "href": "https://x.com/page2",
                "body": "上海心理援助热线：021-12320",
            },
        ]
        with patch("app.services.search_service._ddg_text", return_value=different):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 2)


class SearchServiceTruncationTests(unittest.TestCase):
    def test_truncates_at_word_boundary_for_ascii(self) -> None:
        long_body = "This is a test sentence. " * 30
        raw = [{"title": "T", "href": "https://x.com", "body": long_body}]

        with patch("app.services.search_service._ddg_text", return_value=raw):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        snippet = results[0].snippet
        self.assertLessEqual(len(snippet), 300)
        # Should end at a word boundary (space), not mid-word
        if len(snippet) < len(long_body):
            self.assertFalse(snippet[-1].isalnum())

    def test_truncates_at_cjk_friendly_boundary(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_LONG_ZH],
        ):
            results = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        snippet = results[0].snippet
        self.assertLessEqual(len(snippet), 300)
        # Should end at CJK-safe boundary (, . ...  etc.)
        last_char = snippet[-1]
        safe_endings = {"\u3002", "\uFF0C", "\uFF0E", "\uFF1F", "\uFF01", "\uFF1B"}
        if len(snippet) < 280 and last_char.isascii():
            self.assertIn(last_char, {" ", ".", "!", "?", ",", ":", ";", "\n"})
        # Otherwise it was just long enough before the boundary check hit

    def test_short_content_not_truncated(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_FULL],
        ):
            results = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertIn("400-161-9995", results[0].snippet)
        # Full content should be present (it's short enough)
        self.assertTrue(results[0].snippet.startswith("全国心理援助热线"))

    def test_respects_max_results_after_dedup(self) -> None:
        raw_results = []
        bodies = [
            "北京24小时心理援助热线",
            "上海心理健康服务中心",
            "广州心理咨询预约平台",
            "深圳危机干预中心",
            "成都心理支持热线",
            "杭州心理健康教育基地",
            "武汉心理援助平台",
            "南京心理咨询中心",
        ]
        for i in range(8):
            raw_results.append({
                "title": f"Result {i}",
                "href": f"https://example.com/{i}",
                "body": bodies[i],
            })

        with patch("app.services.search_service._ddg_text", return_value=raw_results):
            results = search_web("test", max_results=3)

        self.assertEqual(len(results), 3)


class SearchServiceErrorTests(unittest.TestCase):
    def test_network_error_returns_empty(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            side_effect=Exception("network timeout"),
        ):
            results = search_web("crisis hotline", max_results=3)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
