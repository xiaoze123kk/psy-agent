from __future__ import annotations

from scripts.live_smoke import CASES, contains_expected_date, contains_expected_source, diagnose_failure


def test_cases_pin_current_fact_dates() -> None:
    pinned = {case.id: case.expected_date for case in CASES}
    source_hosts = {case.id: case.expected_source_hosts for case in CASES}

    assert pinned["zhang_xuefeng_death_time"] == "2026年3月24日15时50分"
    assert pinned["trump_china_visit"] == "2026年5月13日至15日"
    assert "chisa.edu.cn" in source_hosts["zhang_xuefeng_death_time"]
    assert "news.cctv.com" in source_hosts["trump_china_visit"]


def test_contains_expected_date_tolerates_spacing() -> None:
    case = CASES[1]

    assert contains_expected_date("特朗普将于 2026 年 5 月 13 日至 15 日访华。", case)


def test_contains_expected_date_accepts_chinese_to_range() -> None:
    case = CASES[1]

    assert contains_expected_date("特朗普总统这次访华是2026年5月13日到15日。", case)


def test_contains_expected_source_accepts_trusted_direct_source_url() -> None:
    case = CASES[1]

    assert contains_expected_source(
        "美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。\n"
        "https://news.cctv.com/2026/05/11/ARTIgIZRwuDymw7gaEi5DYW2260511.shtml",
        case,
    )


def test_contains_expected_source_rejects_public_search_page_url() -> None:
    case = CASES[1]

    assert not contains_expected_source(
        "美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。\n"
        "https://www.sogou.com/web?query=%E7%89%B9%E6%9C%97%E6%99%AE",
        case,
    )


def test_diagnose_provider_when_direct_probe_lacks_expected_date() -> None:
    case = CASES[0]
    chat_payload = {
        "assistant_message": {
            "assistant_text": "张雪峰于2026年3月24日15时50分在苏州逝世。",
        },
        "trace_summary": {
            "tooling": {
                "tool_names": ["web_search"],
                "status_counts": {"completed": 1},
            }
        },
    }

    diagnosis = diagnose_failure(case, provider_text="", provider_error=None, chat_payload=chat_payload)

    assert diagnosis.layer == "provider"
    assert "direct provider probe" in diagnosis.reason


def test_diagnose_prefetch_when_chat_trace_missing_web_search() -> None:
    case = CASES[0]
    chat_payload = {
        "assistant_message": {"assistant_text": "张雪峰老师还健在。"},
        "trace_summary": {"tooling": {"tool_names": [], "status_counts": {}}},
    }

    diagnosis = diagnose_failure(
        case,
        provider_text=(
            "张雪峰于2026年3月24日15时50分在苏州逝世。\n"
            "http://www.chisa.edu.cn/general/202603/t20260325_2111458613.html"
        ),
        provider_error=None,
        chat_payload=chat_payload,
    )

    assert diagnosis.layer == "prefetch"
    assert "web_search" in diagnosis.reason


def test_diagnose_fallback_when_prefetch_completed_but_answer_missing_date() -> None:
    case = CASES[1]
    chat_payload = {
        "assistant_message": {"assistant_text": "特朗普上一次访华是在2017年11月。"},
        "trace_summary": {
            "tooling": {
                "tool_names": ["web_search"],
                "status_counts": {"completed": 1},
            }
        },
    }

    diagnosis = diagnose_failure(
        case,
        provider_text=(
            "美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。\n"
            "https://news.cctv.com/2026/05/11/ARTIgIZRwuDymw7gaEi5DYW2260511.shtml"
        ),
        provider_error=None,
        chat_payload=chat_payload,
    )

    assert diagnosis.layer == "fallback"
    assert "expected date" in diagnosis.reason


def test_diagnose_provider_when_direct_probe_only_returns_search_page_source() -> None:
    case = CASES[1]
    chat_payload = {
        "assistant_message": {"assistant_text": "特朗普访华是2026年5月13日至15日。"},
        "trace_summary": {
            "tooling": {
                "tool_names": ["web_search"],
                "status_counts": {"completed": 1},
            }
        },
    }

    diagnosis = diagnose_failure(
        case,
        provider_text=(
            "美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。\n"
            "https://www.sogou.com/web?query=%E7%89%B9%E6%9C%97%E6%99%AE"
        ),
        provider_error=None,
        chat_payload=chat_payload,
    )

    assert diagnosis.layer == "provider"
    assert "trusted direct source" in diagnosis.reason
