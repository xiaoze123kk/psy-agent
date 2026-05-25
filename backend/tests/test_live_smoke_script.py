from __future__ import annotations

from scripts.live_smoke import CASES, contains_expected_date, diagnose_failure


def test_cases_pin_current_fact_dates() -> None:
    pinned = {case.id: case.expected_date for case in CASES}

    assert pinned["zhang_xuefeng_death_time"] == "2026年3月24日15时50分"
    assert pinned["trump_china_visit"] == "2026年5月13日至15日"


def test_contains_expected_date_tolerates_spacing() -> None:
    case = CASES[1]

    assert contains_expected_date("特朗普将于 2026 年 5 月 13 日至 15 日访华。", case)


def test_contains_expected_date_accepts_chinese_to_range() -> None:
    case = CASES[1]

    assert contains_expected_date("特朗普总统这次访华是2026年5月13日到15日。", case)


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
        provider_text="张雪峰于2026年3月24日15时50分在苏州逝世。",
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
        provider_text="美国总统特朗普将于2026年5月13日至15日对中国进行国事访问。",
        provider_error=None,
        chat_payload=chat_payload,
    )

    assert diagnosis.layer == "fallback"
    assert "expected date" in diagnosis.reason
