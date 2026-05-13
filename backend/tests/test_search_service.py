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
    "body": "热线电话 &amp; 在线咨询 心理健康服务",
}
_SEARCH_RESULT_LONG_ZH = {
    "title": "心理援助热线",
    "href": "https://example.com/long",
    "body": "全国心理援助热线是为公众提供专业心理支持的公益服务。当您感到焦虑、抑郁或需要倾诉时，可以随时拨打热线电话获得帮助。经过专业培训的咨询师会倾听您的困扰，并提供有效的支持和建议。",
}
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
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理援助")
        self.assertFalse(results[0].snippet.endswith("..."))

    def test_removes_html_entities(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_HTML_ENTITY],
        ):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理&援助")
        self.assertNotIn("&amp;", results[0].snippet)

    def test_empty_query_returns_empty(self) -> None:
        with patch("app.services.search_service._ddg_text", return_value=[]):
            results, _ = search_web("   ", max_results=3)

        self.assertEqual(results, [])

    def test_filters_empty_titles_and_snippets(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_NEARLY_EMPTY, _SEARCH_RESULT_FULL],
        ):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "心理援助热线")

    def test_filters_results_without_url(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_MISSING_URL, _SEARCH_RESULT_FULL],
        ):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/hotline")


class SearchServiceDedupTests(unittest.TestCase):
    def test_deduplicates_by_url(self) -> None:
        same_url_results = [
            {"title": "A", "href": "https://x.com/same", "body": "Content A with more words for testing."},
            {"title": "B", "href": "https://x.com/same", "body": "Content B with more words for testing."},
        ]
        with patch("app.services.search_service._ddg_text", return_value=same_url_results):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)

    def test_deduplicates_by_snippet_similarity(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_FULL, _SEARCH_RESULT_DUPLICATE_CONTENT],
        ):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/hotline")

    def test_keeps_different_content_same_domain(self) -> None:
        different = [
            {
                "title": "Hotline A",
                "href": "https://x.com/page1",
                "body": "北京心理援助热线：010-82951332 提供24小时服务。",
            },
            {
                "title": "Hotline B",
                "href": "https://x.com/page2",
                "body": "上海心理援助热线：021-12320 提供服务支持。",
            },
        ]
        with patch("app.services.search_service._ddg_text", return_value=different):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 2)


class SearchServiceTruncationTests(unittest.TestCase):
    def test_truncates_at_word_boundary_for_ascii(self) -> None:
        long_body = "This is a test sentence. " * 30
        raw = [{"title": "T", "href": "https://x.com", "body": long_body}]

        with patch("app.services.search_service._ddg_text", return_value=raw):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 1)
        snippet = results[0].snippet
        self.assertLessEqual(len(snippet), 300)
        if len(snippet) < len(long_body):
            self.assertFalse(snippet[-1].isalnum())

    def test_truncates_at_cjk_friendly_boundary(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_LONG_ZH],
        ):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        snippet = results[0].snippet
        self.assertLessEqual(len(snippet), 300)
        last_char = snippet[-1]
        if len(snippet) < 280 and last_char.isascii():
            self.assertIn(last_char, {" ", ".", "!", "?", ",", ":", ";", "\n"})

    def test_short_content_not_truncated(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[_SEARCH_RESULT_FULL],
        ):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertIn("400-161-9995", results[0].snippet)
        self.assertTrue(results[0].snippet.startswith("全国心理援助热线"))

    def test_respects_max_results_after_dedup(self) -> None:
        raw_results = []
        bodies = [
            "北京24小时心理援助热线电话提供专业咨询服务",
            "上海心理健康服务中心提供面对面咨询支持",
            "广州心理咨询预约平台可在线预约咨询师",
            "深圳危机干预中心提供紧急心理援助服务",
            "成都心理支持热线为市民提供免费咨询",
            "杭州心理健康教育基地开展公益心理讲座",
            "武汉心理援助平台整合全市咨询资源信息",
            "南京心理咨询中心提供专业的心理评估",
        ]
        for i in range(8):
            raw_results.append({
                "title": f"Result {i}",
                "href": f"https://example.com/{i}",
                "body": bodies[i],
            })

        with patch("app.services.search_service._ddg_text", return_value=raw_results):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 3)


class SearchServiceScoringTests(unittest.TestCase):
    def test_search_result_has_score_field(self) -> None:
        sr = SearchResult(title="T", url="https://x.com", snippet="S")
        self.assertEqual(sr.score, 0)
        sr2 = SearchResult(title="T", url="https://x.com", snippet="S", score=105)
        self.assertEqual(sr2.score, 105)

    def test_gov_domain_scores_higher_than_random(self) -> None:
        gov = {"title": "国家卫健委", "href": "https://www.nhc.gov.cn/health", "body": "国家卫生健康委员会心理援助热线资源汇总查询。"}
        random = {"title": "某博客", "href": "https://blog.example.com/hotline", "body": "个人博客分享心理援助热线使用经验。"}

        with patch("app.services.search_service._ddg_text", return_value=[random, gov]):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 2)
        # gov should be first because it scores much higher
        self.assertIn("nhc.gov.cn", results[0].url)
        self.assertGreater(results[0].score, results[1].score)

    def test_edu_domain_scores_higher_than_random(self) -> None:
        edu = {"title": "北大心理系", "href": "https://www.psych.pku.edu.cn/counseling", "body": "北京大学心理学系提供专业心理咨询服务介绍。"}
        random = {"title": "某论坛", "href": "https://bbs.example.com/thread/123", "body": "论坛用户分享个人心理咨询经验与感受。"}

        with patch("app.services.search_service._ddg_text", return_value=[random, edu]):
            results, _ = search_web("心理咨询", max_results=3)

        self.assertEqual(len(results), 2)
        self.assertIn("pku.edu.cn", results[0].url)
        self.assertGreater(results[0].score, results[1].score)

    def test_baike_scores_higher_than_random(self) -> None:
        baike = {"title": "心理援助热线", "href": "https://baike.baidu.com/item/心理援助热线", "body": "心理援助热线是由专业机构设立的公益服务电话。"}
        random = {"title": "随便说说", "href": "https://random.example.com/hotline", "body": "我觉得心理援助热线还挺有用的分享一些经验。"}

        with patch("app.services.search_service._ddg_text", return_value=[random, baike]):
            results, _ = search_web("心理援助热线", max_results=3)

        self.assertEqual(len(results), 2)
        self.assertIn("baike.baidu.com", results[0].url)
        self.assertGreater(results[0].score, results[1].score)

    def test_https_scores_higher_than_http(self) -> None:
        https = {"title": "安全页面", "href": "https://secure.example.com/hotline", "body": "安全的心理援助资源信息页面。"}
        http = {"title": "非安全页面", "href": "http://insecure.example.com/hotline", "body": "非安全的心理援助资源介绍。"}

        with patch("app.services.search_service._ddg_text", return_value=[http, https]):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 2)
        self.assertGreater(results[0].score, results[1].score)
        self.assertTrue(results[0].url.startswith("https://"))

    def test_shallow_path_scores_higher_than_deep(self) -> None:
        shallow = {"title": "心理健康主页", "href": "https://example.com/mental-health", "body": "心理健康服务介绍页面提供咨询。"}
        deep = {"title": "论坛帖子", "href": "https://example.com/forum/thread/999/page/3", "body": "论坛心理健康讨论帖子分享。"}

        with patch("app.services.search_service._ddg_text", return_value=[deep, shallow]):
            results, _ = search_web("心理健康", max_results=3)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://example.com/mental-health")
        self.assertGreater(results[0].score, results[1].score)

    def test_authority_title_scores_higher(self) -> None:
        authority = {"title": "北京心理援助中心官方热线", "href": "https://example.com/a", "body": "北京心理援助中心提供专业心理咨询服务。"}
        generic = {"title": "聊聊心理援助", "href": "https://example.com/b", "body": "分享心理援助服务的个人使用心得。"}

        with patch("app.services.search_service._ddg_text", return_value=[generic, authority]):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 2)
        self.assertGreater(results[0].score, results[1].score)
        self.assertIn("北京", results[0].title)

    def test_respects_max_results_after_sorting(self) -> None:
        items = []
        for i in range(6):
            items.append({
                "title": f"Result {i}",
                "href": f"https://x{i}.com/page",
                "body": f"内容 {i} 心理援助信息。",
            })

        with patch("app.services.search_service._ddg_text", return_value=items):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 3)

    def test_score_preserved_on_result(self) -> None:
        raw = [{"title": "T", "href": "https://example.com", "body": "心理援助热线电话提供咨询服务。"}]

        with patch("app.services.search_service._ddg_text", return_value=raw):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0].score, int)


class SearchServiceLowInfoFilterTests(unittest.TestCase):
    def test_filters_out_short_snippet(self) -> None:
        short = {"title": "测试", "href": "https://x.com", "body": "短"}
        good = {"title": "完整信息", "href": "https://x.com/2", "body": "这是一条完整的心理援助热线信息内容。"}

        with patch("app.services.search_service._ddg_text", return_value=[short, good]):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://x.com/2")

    def test_filters_out_click_to_read_more(self) -> None:
        boilerplate = {"title": "某文章", "href": "https://x.com/click", "body": "点击阅读更多内容查看更多详情。"}
        good = {"title": "热线信息", "href": "https://x.com/2", "body": "北京心理援助热线提供24小时免费心理咨询服务。"}

        with patch("app.services.search_service._ddg_text", return_value=[boilerplate, good]):
            results, _ = search_web("心理援助", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://x.com/2")

    def test_keeps_low_cjk_but_high_latin_info(self) -> None:
        latin = {
            "title": "APA Guidelines",
            "href": "https://apa.org/guidelines",
            "body": "The American Psychological Association provides evidence-based guidelines for mental health professionals working with diverse populations.",
        }

        with patch("app.services.search_service._ddg_text", return_value=[latin]):
            results, _ = search_web("psychological guidelines", max_results=3)

        self.assertEqual(len(results), 1)

    def test_filters_out_empty_cjk_latinsnippet(self) -> None:
        empty = {"title": "Empty", "href": "https://x.com", "body": "a b c d"}

        with patch("app.services.search_service._ddg_text", return_value=[empty]):
            results, _ = search_web("test", max_results=3)

        self.assertEqual(len(results), 0)


class SearchServiceErrorTests(unittest.TestCase):
    def test_network_error_returns_empty_and_error_message(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            side_effect=Exception("network timeout"),
        ):
            results, err = search_web("crisis hotline", max_results=3)
        self.assertEqual(results, [])
        self.assertEqual(err, "network_error")

    def test_timeout_returns_empty_and_error_message(self) -> None:
        import time

        def slow_search(*args, **kwargs):
            time.sleep(10)
            return []

        with patch("app.services.search_service._ddg_text", side_effect=slow_search):
            results, err = search_web("test", max_results=3, timeout_seconds=0.1)
        self.assertEqual(results, [])
        self.assertEqual(err, "timeout")

    def test_success_returns_no_error(self) -> None:
        with patch(
            "app.services.search_service._ddg_text",
            return_value=[{"title": "X", "href": "https://x.com", "body": "Content body text here."}],
        ):
            results, err = search_web("test", max_results=3)
        self.assertEqual(len(results), 1)
        self.assertIsNone(err)

    def test_empty_query_returns_no_error(self) -> None:
        results, err = search_web("   ", max_results=3)
        self.assertEqual(results, [])
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
