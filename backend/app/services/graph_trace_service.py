from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ConversationTurn, ConversationTurnTrace, utcnow
from app.services.tooling import summarize_tool_events


logger = logging.getLogger(__name__)

MAX_STRING_LENGTH = 160
MAX_LIST_ITEMS = 10
MAX_DICT_ITEMS = 20
MAX_TRACE_STEPS = 12
MAX_MEMORY_REFERENCES = 5
SAFE_POLICY_SCALAR_KEYS = {
    "conversation_move",
    "topic_anchor",
    "button_style",
    "psychologizing_risk",
    "cultural_response_mode",
    "primary_lane",
}
SAFE_VOICE_CONTRACT_KEYS = {
    "voice_mode",
    "analysis_depth",
    "question_budget",
    "sentence_budget",
    "opening_preference",
    "closing_preference",
    "humor_allowed",
}
SAFE_ADAPTATION_KEYS = {
    "avoid_analysis_turns",
    "avoid_questions_turns",
    "avoid_safety_check_turns",
    "prefer_direct_anchor_response_turns",
    "last_correction_type",
}

BLOCKED_KEYS = {
    "assistant_text",
    "content",
    "context_text",
    "messages",
    "normalized_text",
    "recent_messages",
    "referenced_counseling_examples",
    "referenced_memories",
    "retrieved_counseling_examples",
    "retrieved_memories",
    "response_contract",
    "session_summary",
    "text",
    "user_text",
    "voice_transcript",
}

SAFE_DIRECT_KEYS = {
    "audit_tags",
    "control_category",
    "control_confidence",
    "control_reasons",
    "conversation_quality_trace",
    "conversation_move_policy",
    "delivery_status",
    "example_ids",
    "example_source_keys",
    "failure_reason",
    "intent",
    "memory_policy",
    "memory_policy_reason",
    "memory_candidate_count",
    "memory_write_decision_count",
    "memory_write_decisions",
    "node_name",
    "rag_skipped_reason",
    "rag_trace_summary",
    "rag_used",
    "requires_safety_check",
    "retryable",
    "retrieved_example_count",
    "retrieved_memory_count",
    "risk_level",
    "risk_reason_codes",
    "risk_reasons",
    "risk_source",
    "route_priority",
    "semantic_risk",
    "should_write_memory",
    "validator_blocked",
    "validator_reasons",
    "validator_severity",
    "experience_validator_warnings",
    "experience_validator_blocking_reasons",
}

SAFE_RISK_FORMULATION_KEYS = {
    "labels",
    "observed_reasons",
    "reason_codes",
    "requires_safety_check",
    "risk_source",
    "semantic_risk",
    "uncertainty",
}


def _trim_string(value: object) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_STRING_LENGTH:
        return text
    return text[: MAX_STRING_LENGTH - 3].rstrip() + "..."


def _sanitize_value(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _trim_string(value)
    if isinstance(value, list | tuple):
        return [_sanitize_value(item) for item in list(value)[:MAX_LIST_ITEMS]]
    if isinstance(value, dict):
        summary: dict[str, object] = {}
        for key, item in list(value.items())[:MAX_DICT_ITEMS]:
            key_text = str(key)
            if key_text in BLOCKED_KEYS:
                continue
            summary[key_text] = _sanitize_value(item)
        return summary
    return _trim_string(value)


def _count_items(value: object) -> int:
    if isinstance(value, list | tuple | dict):
        return len(value)
    return 0


def _summarize_memory_write_decisions(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    decisions: list[dict[str, object]] = []
    for item in value[:MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        decision = {
            key: _sanitize_value(item[key])
            for key in ("status", "reason", "memory_type")
            if key in item
        }
        if decision:
            decisions.append(decision)
    return decisions


def _summarize_risk_formulation(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _sanitize_value(value[key])
        for key in SAFE_RISK_FORMULATION_KEYS
        if key in value and value[key] not in ("", [], {})
    }


def _safe_topic_anchor(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _sanitize_value(value[key])
            for key in ("type", "anchor_type", "kind")
            if key in value and value[key] not in ("", [], {})
        }
    text = str(value or "").strip()
    if "/" in text:
        return text.split("/", 1)[0]
    return _sanitize_value(text)


def _summarize_intent_lanes(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    lanes: list[dict[str, object]] = []
    for lane in value[:MAX_LIST_ITEMS]:
        if not isinstance(lane, dict):
            continue
        summary = {
            key: _sanitize_value(lane[key])
            for key in ("kind", "anchor_type", "priority", "handling")
            if lane.get(key) not in (None, "", [], {})
        }
        clues = lane.get("user_clues")
        if isinstance(clues, list):
            summary["user_clue_count"] = len(clues)
        if summary:
            lanes.append(summary)
    return lanes


def summarize_conversation_move_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, object] = {}
    for key in SAFE_POLICY_SCALAR_KEYS:
        if key not in value or value[key] in ("", [], {}):
            continue
        summary[key] = _safe_topic_anchor(value[key]) if key == "topic_anchor" else _sanitize_value(value[key])

    lanes = _summarize_intent_lanes(value.get("intent_lanes"))
    if lanes:
        summary["intent_lanes"] = lanes
        summary["intent_lane_count"] = len(value.get("intent_lanes") or [])

    voice_contract = value.get("ningyu_voice_contract")
    if isinstance(voice_contract, dict):
        contract_summary = {
            key: _sanitize_value(voice_contract[key])
            for key in SAFE_VOICE_CONTRACT_KEYS
            if key in voice_contract and voice_contract[key] not in ("", [], {})
        }
        if contract_summary:
            summary["ningyu_voice_contract"] = contract_summary

    adaptation = value.get("adaptation_state")
    if isinstance(adaptation, dict):
        adaptation_summary = {
            key: _sanitize_value(adaptation[key])
            for key in SAFE_ADAPTATION_KEYS
            if key in adaptation and adaptation[key] not in ("", [], {})
        }
        if adaptation_summary:
            summary["adaptation_state"] = adaptation_summary

    evidence = value.get("anchor_evidence")
    if isinstance(evidence, dict):
        evidence_summary = {
            key: _sanitize_value(evidence[key])
            for key in ("anchor_type", "response_mode")
            if key in evidence and evidence[key] not in ("", [], {})
        }
        if isinstance(evidence.get("user_clues"), list):
            evidence_summary["user_clue_count"] = len(evidence["user_clues"])
        if isinstance(evidence.get("forbidden_claims"), list):
            evidence_summary["forbidden_claim_count"] = len(evidence["forbidden_claims"])
        if evidence_summary:
            summary["anchor_evidence"] = evidence_summary
    return _sanitize_summary(summary)


def summarize_node_output(node_name: str, node_output: object) -> dict[str, object]:
    if not isinstance(node_output, dict):
        return {"node_output_type": type(node_output).__name__}

    summary: dict[str, object] = {}
    for key in SAFE_DIRECT_KEYS:
        if key in node_output and node_output[key] not in ("", [], {}):
            if key == "conversation_move_policy":
                policy_summary = summarize_conversation_move_policy(node_output[key])
                if policy_summary:
                    summary[key] = policy_summary
            else:
                summary[key] = _sanitize_value(node_output[key])

    if "risk_formulation" in node_output:
        risk_formulation = _summarize_risk_formulation(node_output["risk_formulation"])
        if risk_formulation:
            summary["risk_formulation"] = risk_formulation

    if "retrieved_memories" in node_output:
        summary["retrieved_memory_count"] = _count_items(node_output["retrieved_memories"])
    if "retrieved_counseling_examples" in node_output:
        summary["retrieved_example_count"] = _count_items(node_output["retrieved_counseling_examples"])
    if "memory_candidates" in node_output:
        summary["memory_candidate_count"] = _count_items(node_output["memory_candidates"])
    if "memory_write_decisions" in node_output:
        summary["memory_write_decision_count"] = _count_items(node_output["memory_write_decisions"])
        decisions = _summarize_memory_write_decisions(node_output["memory_write_decisions"])
        if decisions:
            summary["memory_write_decisions"] = decisions
    if "tool_events" in node_output:
        tool_summary = summarize_tool_events(node_output.get("tool_events"))
        if int(tool_summary.get("tool_count") or 0) > 0:
            summary["tool_event_count"] = tool_summary["tool_count"]
            summary["tool_names"] = tool_summary.get("tool_names", [])
            summary["tool_status_counts"] = tool_summary.get("status_counts", {})
            summary["tool_error_count"] = tool_summary.get("error_count", 0)
    if isinstance(node_output.get("tool_trace_summary"), dict):
        summary["tool_trace_summary"] = _sanitize_summary(node_output["tool_trace_summary"])

    summary["node_name"] = _trim_string(node_name)
    return _sanitize_summary(summary)


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [_trim_string(item) for item in value[:MAX_LIST_ITEMS] if str(item or "").strip()]


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0, int(value))
    return None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _first_present(*values: object) -> object | None:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _optional_text(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    text = str(value)
    return "" if text.lower() == "none" else text


def _latest_trace_value(graph_trace: list[dict[str, object]], key: str) -> object | None:
    for record in reversed(graph_trace):
        summary = _as_dict(record.get("output_summary"))
        value = summary.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _latest_trace_int(graph_trace: list[dict[str, object]], key: str) -> int | None:
    return _as_int(_latest_trace_value(graph_trace, key))


def _latest_trace_bool(graph_trace: list[dict[str, object]], key: str) -> bool | None:
    return _as_bool(_latest_trace_value(graph_trace, key))


def _max_present_int(*values: object) -> int:
    ints = [_as_int(value) for value in values]
    return max((value for value in ints if value is not None), default=0)


def _safe_memory_references(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    references: list[dict[str, object]] = []
    for item in list(value)[:MAX_MEMORY_REFERENCES]:
        if not isinstance(item, dict):
            continue
        reference = {
            "memory_id": _trim_string(item.get("memory_id", "")),
            "memory_type": _trim_string(item.get("memory_type", "")),
            "content": _trim_string(item.get("content", "")),
        }
        if reference["memory_id"] and reference["content"]:
            references.append(reference)
    return references


def _safe_step(record: dict[str, object]) -> dict[str, object]:
    output_summary = _sanitize_summary(record.get("output_summary") or {})
    return _sanitize_summary(
        {
            "sequence": _as_int(record.get("sequence")),
            "trace_type": str(record.get("trace_type") or "graph_node"),
            "node_name": str(record.get("node_name") or "unknown"),
            "status": str(record.get("status") or "completed"),
            "duration_ms": _as_int(record.get("duration_ms")) or 0,
            "reason_codes": _as_string_list(record.get("reason_codes")),
            "error_code": record.get("error_code"),
            "output_summary": output_summary,
        }
    )


def extract_reason_codes(summary: dict[str, object]) -> list[str]:
    codes: list[str] = []
    codes.extend(_as_string_list(summary.get("risk_reason_codes")))
    codes.extend(_as_string_list(summary.get("validator_reasons")))
    codes.extend(_as_string_list(summary.get("experience_validator_blocking_reasons")))
    codes.extend(_as_string_list(summary.get("experience_validator_warnings")))
    if isinstance(summary.get("risk_formulation"), dict):
        codes.extend(_as_string_list(summary["risk_formulation"].get("reason_codes")))
    for key in ("failure_reason", "rag_skipped_reason", "memory_policy_reason"):
        value = summary.get(key)
        if isinstance(value, str) and value:
            codes.append(value)
    return list(dict.fromkeys(codes))[:MAX_LIST_ITEMS]


def _sanitize_summary(summary: object) -> dict[str, object]:
    sanitized = _sanitize_value(summary)
    if not isinstance(sanitized, dict):
        return {}
    return sanitized


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class GraphTraceCollector:
    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []
        self._sequence = 0
        self._last_started_at = utcnow()
        self._last_tick = perf_counter()

    @property
    def records(self) -> list[dict[str, object]]:
        return list(self._records)

    def record_node(
        self,
        node_name: str,
        node_output: object,
        *,
        trace_type: str = "graph_node",
        status: str = "completed",
        error_code: str | None = None,
    ) -> dict[str, object]:
        completed_at = utcnow()
        completed_tick = perf_counter()
        duration_ms = max(0, int((completed_tick - self._last_tick) * 1000))
        output_summary = summarize_node_output(node_name, node_output)
        record = {
            "sequence": self._sequence,
            "trace_type": trace_type,
            "node_name": _trim_string(node_name),
            "status": status,
            "started_at": self._last_started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "output_summary": output_summary,
            "reason_codes": extract_reason_codes(output_summary),
            "error_code": error_code,
        }
        self._records.append(record)
        self._sequence += 1
        self._last_started_at = completed_at
        self._last_tick = completed_tick
        return record


def build_delivery_trace(result: dict[str, object], *, node_name: str = "delivery_result") -> list[dict[str, object]]:
    collector = GraphTraceCollector()
    status = "failed" if result.get("delivery_status") == "failed_no_reply" else "completed"
    error_code = str(result.get("failure_reason") or "") or None
    collector.record_node(node_name, result, trace_type="service_stage", status=status, error_code=error_code)
    return collector.records


def build_trace_summary(graph_trace: list[dict[str, object]], result: dict[str, object]) -> dict[str, object]:
    failed_nodes = [
        str(record.get("node_name") or "")
        for record in graph_trace
        if str(record.get("status") or "completed") != "completed"
    ]
    duration_records = [
        record for record in graph_trace if isinstance(record.get("duration_ms"), int | float)
    ]
    slowest = max(duration_records, key=lambda record: int(record.get("duration_ms") or 0), default=None)
    delivery_status = str(
        _first_present(
            result.get("delivery_status"),
            _latest_trace_value(graph_trace, "delivery_status"),
            "generated",
        )
    )
    failure_reason = _first_present(result.get("failure_reason"), _latest_trace_value(graph_trace, "failure_reason"))
    validator_reasons = _as_string_list(result.get("validator_reasons")) or _as_string_list(
        _latest_trace_value(graph_trace, "validator_reasons")
    )
    experience_validator_warnings = _as_string_list(result.get("experience_validator_warnings")) or _as_string_list(
        _latest_trace_value(graph_trace, "experience_validator_warnings")
    )
    experience_validator_blocking_reasons = _as_string_list(
        result.get("experience_validator_blocking_reasons")
    ) or _as_string_list(_latest_trace_value(graph_trace, "experience_validator_blocking_reasons"))
    validator_severity = str(
        _first_present(
            result.get("validator_severity"),
            _latest_trace_value(graph_trace, "validator_severity"),
            "passed" if not validator_reasons and not experience_validator_warnings else "warning",
        )
    )
    referenced_memories = _safe_memory_references(result.get("referenced_memories"))
    retrieved_memory_count = _max_present_int(
        result.get("retrieved_memory_count"),
        _latest_trace_int(graph_trace, "retrieved_memory_count"),
        len(referenced_memories),
    )
    memory_write_decision_count = _max_present_int(
        result.get("memory_write_decision_count"),
        _latest_trace_int(graph_trace, "memory_write_decision_count"),
        len(result.get("memory_write_decisions", [])) if isinstance(result.get("memory_write_decisions"), list) else None,
    )
    rag_used = _as_bool(result.get("rag_used"))
    if rag_used is None:
        rag_used = _latest_trace_bool(graph_trace, "rag_used") or False
    rag_trace_summary = _sanitize_summary(
        _first_present(
            result.get("rag_trace_summary"),
            _latest_trace_value(graph_trace, "rag_trace_summary"),
            {},
        )
    )
    validator_blocked = _as_bool(result.get("validator_blocked"))
    if validator_blocked is None:
        validator_blocked = _latest_trace_bool(graph_trace, "validator_blocked") or False
    conversation_quality = _sanitize_summary(
        _first_present(
            result.get("conversation_quality_trace"),
            _latest_trace_value(graph_trace, "conversation_quality_trace"),
            {},
        )
    )
    steps = [_safe_step(record) for record in graph_trace[:MAX_TRACE_STEPS]]
    tooling = _sanitize_summary(result.get("tool_trace_summary") or {})
    if not tooling:
        tooling = summarize_tool_events(result.get("tool_events"))

    summary = {
        "node_count": len(graph_trace),
        "failed_nodes": [node for node in failed_nodes if node][:MAX_LIST_ITEMS],
        "slowest_node": (
            {
                "node_name": str(slowest.get("node_name") or ""),
                "duration_ms": int(slowest.get("duration_ms") or 0),
            }
            if slowest
            else None
        ),
        "total_graph_duration_ms": sum(int(record.get("duration_ms") or 0) for record in duration_records),
        "delivery_status": delivery_status,
        "failure_reason": failure_reason,
        "validator_blocked": validator_blocked,
        "mode": {
            "intent": str(_first_present(result.get("intent"), _latest_trace_value(graph_trace, "intent"), "other")),
            "control_category": str(
                _first_present(result.get("control_category"), _latest_trace_value(graph_trace, "control_category"), "normal_support")
            ),
            "route_priority": str(
                _first_present(result.get("route_priority"), _latest_trace_value(graph_trace, "route_priority"), "P2_support")
            ),
            "risk_level": str(_first_present(result.get("risk_level"), _latest_trace_value(graph_trace, "risk_level"), "L0")),
        },
        "memory": {
            "memory_mode": result.get("memory_mode"),
            "retrieved_count": retrieved_memory_count,
            "referenced_count": len(referenced_memories),
            "referenced_memories": referenced_memories,
            "should_write": bool(result.get("should_write_memory", False)),
            "write_decision_count": memory_write_decision_count,
            "write_decisions": _summarize_memory_write_decisions(result.get("memory_write_decisions")),
        },
        "rag": {
            "used": rag_used,
            "skipped_reason": _optional_text(
                _first_present(result.get("rag_skipped_reason"), _latest_trace_value(graph_trace, "rag_skipped_reason"), "")
            ),
            "trace": rag_trace_summary,
            "retrieved_example_count": _max_present_int(
                result.get("retrieved_example_count"),
                _latest_trace_int(graph_trace, "retrieved_example_count"),
                len(result.get("referenced_counseling_examples", []))
                if isinstance(result.get("referenced_counseling_examples"), list)
                else None,
            ),
            "example_ids": _as_string_list(result.get("example_ids")),
            "example_source_keys": _as_string_list(result.get("example_source_keys")),
        },
        "validator": {
            "checked": any(str(record.get("node_name") or "") == "response_validator" for record in graph_trace),
            "blocked": validator_blocked,
            "reasons": validator_reasons,
            "severity": validator_severity,
            "warnings": experience_validator_warnings,
            "experience_blocking_reasons": experience_validator_blocking_reasons,
            "delivery_status": delivery_status,
        },
        "conversation_quality": conversation_quality,
        "tooling": tooling,
        "fallback": {
            "triggered": delivery_status != "generated" or bool(failure_reason),
            "reason": failure_reason,
            "retryable": bool(result.get("retryable", False)),
        },
        "steps": steps,
    }
    return _sanitize_summary(summary)


def persist_turn_traces(
    db: Session,
    *,
    turn: ConversationTurn,
    traces: list[dict[str, object]],
) -> None:
    if not traces:
        return
    try:
        for sequence, record in enumerate(traces):
            node_name = str(record.get("node_name") or "unknown")[:80]
            output_summary = summarize_node_output(node_name, record.get("output_summary") or {})
            reason_codes = _as_string_list(record.get("reason_codes"))
            db.add(
                ConversationTurnTrace(
                    turn_id=turn.id,
                    user_id=turn.user_id,
                    thread_id=turn.thread_id,
                    sequence=sequence,
                    trace_type=str(record.get("trace_type") or "graph_node"),
                    node_name=node_name,
                    status=str(record.get("status") or "completed")[:24],
                    started_at=_coerce_datetime(record.get("started_at")) or utcnow(),
                    completed_at=_coerce_datetime(record.get("completed_at")),
                    duration_ms=max(0, int(record.get("duration_ms") or 0)),
                    output_summary=output_summary,
                    reason_codes=reason_codes or extract_reason_codes(output_summary),
                    error_code=(str(record.get("error_code"))[:80] if record.get("error_code") else None),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist conversation turn graph trace.")
