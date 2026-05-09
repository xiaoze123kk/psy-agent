from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ConversationTurn, ConversationTurnTrace, utcnow


logger = logging.getLogger(__name__)

MAX_STRING_LENGTH = 160
MAX_LIST_ITEMS = 10
MAX_DICT_ITEMS = 20

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


def summarize_node_output(node_name: str, node_output: object) -> dict[str, object]:
    if not isinstance(node_output, dict):
        return {"node_output_type": type(node_output).__name__}

    summary: dict[str, object] = {}
    for key in SAFE_DIRECT_KEYS:
        if key in node_output and node_output[key] not in ("", [], {}):
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

    summary["node_name"] = _trim_string(node_name)
    return _sanitize_summary(summary)


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [_trim_string(item) for item in value[:MAX_LIST_ITEMS] if str(item or "").strip()]


def extract_reason_codes(summary: dict[str, object]) -> list[str]:
    codes: list[str] = []
    codes.extend(_as_string_list(summary.get("risk_reason_codes")))
    codes.extend(_as_string_list(summary.get("validator_reasons")))
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
        "delivery_status": str(result.get("delivery_status") or "generated"),
        "failure_reason": result.get("failure_reason"),
        "validator_blocked": bool(result.get("validator_blocked", False)),
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
