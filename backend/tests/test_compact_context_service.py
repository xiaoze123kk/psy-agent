from app.services.compact_context_service import (
    build_compact_context_pack,
    estimate_context_budget,
    quality_signals_from_recent_messages,
    should_compact_context,
)


def _msg(index: int, role: str, content: str, **metadata):
    return {
        "id": f"msg-{index}",
        "role": role,
        "content": content,
        "metadata": metadata,
        "risk_level": metadata.get("risk_level"),
        "created_at": f"2026-05-17T12:{index:02d}:00+08:00",
    }


def test_estimate_context_budget_uses_character_fallback():
    budget = estimate_context_budget([_msg(1, "user", "a" * 250)], max_chars=1000)

    assert budget["used_chars"] == 250
    assert budget["max_chars"] == 1000
    assert budget["usage_ratio"] == 0.25
    assert budget["message_count"] == 1


def test_should_compact_when_context_is_long_or_quality_warns():
    messages = [_msg(i, "user", f"消息 {i}") for i in range(14)]

    decision = should_compact_context(
        recent_messages=messages,
        quality_signals={"recent_repetition_risk": "high"},
        max_messages=10,
        max_chars=5000,
    )

    assert decision["should_compact"] is True
    assert "message_threshold" in decision["reasons"]
    assert "quality_repetition_risk" in decision["reasons"]


def test_should_compact_when_forced_even_without_pressure():
    decision = should_compact_context(
        recent_messages=[_msg(1, "user", "还不长")],
        quality_signals={},
        force=True,
    )

    assert decision["should_compact"] is True
    assert "force" in decision["reasons"]


def test_quality_signals_from_recent_messages_summarizes_trace_without_raw_text():
    messages = [
        _msg(
            1,
            "assistant",
            "raw-assistant-answer-that-must-not-leak",
            conversation_quality_trace={
                "turn_shape": {"question_count": 3},
                "policy_snapshot": {
                    "conversation_move": "continue_thread",
                    "topic_anchor_type": "literary",
                },
                "validator_snapshot": {
                    "severity": "repaired",
                    "experience_reasons": ["too_many_questions", "missed_primary_lane"],
                },
                "user_signal": {
                    "explicit_feedback": "none",
                    "next_turn_signal": "corrected",
                },
            },
            conversation_move_policy={
                "suppressed_recent_anchors": ["raw-stale-anchor-that-must-not-leak"],
            },
        ),
        _msg(2, "user", "raw-user-correction-that-must-not-leak"),
    ]

    signals = quality_signals_from_recent_messages(messages)

    assert signals["recent_over_questioning_risk"] == "high"
    assert signals["topic_drift_risk"] == "high"
    assert signals["stale_anchor_misuse_risk"] == "high"
    assert signals["user_correction_signal"] == "corrected"
    assert "raw-assistant-answer" not in str(signals)
    assert "raw-user-correction" not in str(signals)
    assert "raw-stale-anchor" not in str(signals)


def test_build_pack_derives_quality_triggers_from_recent_trace_when_not_explicitly_passed():
    messages = [
        _msg(
            1,
            "assistant",
            "previous answer",
            trace_summary={
                "conversation_quality": {
                    "turn_shape": {"question_count": 2},
                    "policy_snapshot": {
                        "conversation_move": "continue_thread",
                        "topic_anchor_type": "literary",
                    },
                    "validator_snapshot": {
                        "severity": "passed",
                        "experience_reasons": ["too_many_questions"],
                    },
                    "user_signal": {
                        "explicit_feedback": "none",
                        "next_turn_signal": "corrected",
                    },
                }
            },
        ),
        _msg(2, "user", "actually I meant something else"),
    ]

    pack = build_compact_context_pack(recent_messages=messages, risk_level="L0")

    quality = pack["state"]["quality_signals"]
    assert quality["recent_over_questioning_risk"] == "high"
    assert quality["user_correction_signal"] == "corrected"
    assert "quality_over_questioning_risk" in pack["event"]["trigger"]["reason"]
    assert "quality_user_correction_signal" in pack["event"]["trigger"]["reason"]


def test_build_pack_marks_old_anchor_as_stale_when_user_does_not_reuse_it():
    messages = [
        _msg(1, "user", "我刚才说在轮下那个感觉。"),
        _msg(2, "assistant", "你提到了在轮下。"),
        _msg(3, "user", "其实现在就是很生气。"),
        _msg(4, "assistant", "我听到的是生气。"),
        _msg(5, "user", "对，很堵。"),
    ]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={"summary_200chars": "用户早前提到在轮下，后来转向生气和堵。"},
        risk_level="L0",
        max_recent_messages=2,
    )

    assert pack["state"]["stale_threads"][0]["topic"] == "在轮下"
    assert "不要复用" in pack["state"]["stale_threads"][0]["reuse_policy"]
    assert "在轮下" in pack["event"]["summary"]


def test_build_pack_keeps_user_boundaries_and_time_policy_without_long_term_candidates():
    messages = [
        _msg(1, "user", "别一直分析我，也不要连着问。"),
        _msg(2, "assistant", "好，我会放慢。"),
    ]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={},
        risk_level="L0",
    )

    assert pack["schema_version"] == 1
    assert pack["source"] == "runtime_compact_context"
    assert any("分析" in item for item in pack["state"]["user_boundaries"])
    assert any("连着问" in item for item in pack["state"]["interaction_preferences"])
    assert pack["state"]["time_context_policy"]["timezone"] == "Asia/Wuhan"
    assert pack["memory_candidates"] == []


def test_build_pack_uses_asia_wuhan_policy_without_storing_current_time():
    pack = build_compact_context_pack(
        recent_messages=[_msg(1, "user", "现在有点乱。")],
        session_digest={},
        risk_level="L0",
    )

    time_policy = pack["state"]["time_context_policy"]
    assert time_policy["timezone"] == "Asia/Wuhan"
    assert time_policy["source"] == "runtime"
    assert "use_policy" in time_policy
    assert "now" not in time_policy
    assert "local_time" not in time_policy


def test_compact_event_contains_auditable_range_and_trigger_fields():
    messages = [_msg(index, "user", f"消息 {index}") for index in range(1, 7)]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={"summary_200chars": "用户持续在整理压力。"},
        risk_level="L0",
        max_recent_messages=2,
        created_at="2026-05-17T12:31:00+08:00",
    )

    event = pack["event"]
    assert event["type"] == "compact_event"
    assert event["schema_version"] == 1
    assert event["created_at"] == "2026-05-17T12:31:00+08:00"
    assert "trigger" in event
    assert "range" in event
    assert event["range"]["forgotten_turn_ids"] == ["msg-1", "msg-2", "msg-3", "msg-4"]
    assert event["range"]["kept_tail_turn_ids"] == ["msg-5", "msg-6"]
    assert event["quality_flags"]["summary_confidence"] in {"low", "medium"}


def test_build_pack_detects_book_and_jung_demian_anchors():
    messages = [
        _msg(1, "user", "我想到《德米安》和荣格。"),
        _msg(2, "assistant", "这些意象很强。"),
        _msg(3, "user", "现在先说我很烦。"),
        _msg(4, "assistant", "先陪你待在烦里。"),
    ]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={},
        max_recent_messages=2,
    )

    stale_topics = {item["topic"] for item in pack["state"]["stale_threads"]}
    assert "《德米安》" in stale_topics
    assert "荣格" in stale_topics


def test_build_pack_uses_structured_stale_anchor_candidates():
    messages = [
        _msg(1, "user", "前面那个比喻先放一下。"),
        _msg(2, "assistant", "好。"),
        _msg(3, "user", "我现在就是很烦。"),
    ]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={
            "stale_threads": [{"topic": "旧比喻", "reuse_policy": "不要主动带回"}],
            "suppressed_recent_anchors": ["旧作品"],
            "anchor_state": {"recent_anchor": "旧引号锚点", "anchor_status": "stale"},
        },
        max_recent_messages=1,
    )

    stale_topics = {item["topic"] for item in pack["state"]["stale_threads"]}
    assert {"旧比喻", "旧作品", "旧引号锚点"}.issubset(stale_topics)


def test_high_risk_pack_filters_operational_details():
    messages = [
        _msg(1, "user", "我想今晚去桥边，用刀和两片药伤害自己。"),
        _msg(2, "assistant", "先把那个东西放远一点。"),
    ]

    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={"summary_200chars": "用户提到今晚、桥边、刀和两片药。"},
        risk_level="L2",
        quality_signals={"last_quality_issue": "提到桥边和刀"},
    )

    assert pack["state"]["safety_context"]["risk_level"] == "L2"
    for unsafe_detail in ("今晚", "桥边", "刀", "两片药"):
        assert unsafe_detail not in str(pack)
    assert "安全连续性" in pack["state"]["safety_context"]["note"]
