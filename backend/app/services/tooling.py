from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.schemas.common import SafetyAudience

logger = logging.getLogger(__name__)
from app.services.deepseek_client import (
    DEFAULT_MAX_TOOL_ROUNDS,
    ToolChatResult,
    ToolExecutionEvent,
    ToolHandler,
    deepseek_client,
)
from app.services.safety_service import build_safety_resources
from app.services.temporal_context_service import build_temporal_context


LOW_RISK_LEVELS = frozenset({"L0", "L1"})
HIGH_RISK_LEVELS = frozenset({"L2", "L3"})
ALL_RISK_LEVELS = LOW_RISK_LEVELS | HIGH_RISK_LEVELS
MEMORY_TOOL_NAMES = frozenset({"search_memories", "save_memory_summary"})
SAFETY_TOOL_NAMES = frozenset({"get_safety_resources"})
SAFETY_CONTEXT_MEMORY_TYPES = frozenset({"safety_summary", "support_strategy", "preference", "correction", "relationship"})
SAFETY_CONTEXT_TOOL_NAMES = frozenset({"search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"})
BLOCKED_CONTEXT_TOOL_NAMES = frozenset({"get_current_time", "summarize_session"})
MAX_TOOL_PREVIEWS = 5
DEFAULT_DIALOGUE_REPLY_MAX_TOKENS = 900
CURRENT_FACT_QUERY_RE = re.compile(
    r"(去世|逝世|死亡|访华|访美|访中|最新|新闻|什么时候|哪天|日期|时间|今天|昨天|今年|现任|总统|首相|CEO|发生|是否|了吗)"
)
FACT_DATE_RE = re.compile(r"(?:20\d{2}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{1,2}时\d{1,2}分)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*")

VISIBLE_MEMORY_TYPES = {
    "profile",
    "correction",
    "preference",
    "session_summary",
    "recurring_trigger",
    "support_strategy",
    "relationship",
    "state",
    "goal",
}
INTERNAL_MEMORY_TYPES = {"safety_summary"}
ALL_MEMORY_TYPES = VISIBLE_MEMORY_TYPES | INTERNAL_MEMORY_TYPES


def _clean_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    if limit is not None and len(text) > limit:
        return text[: max(limit - 3, 0)].rstrip() + "..."
    return text


def _clamp_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(maximum, coerced))


def _unique_strings(value: object, *, limit: int = 8, item_limit: int = 32) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        item = _clean_text(raw, limit=item_limit)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _normalize_memory_type(memory_type: object) -> str:
    raw = _clean_text(memory_type, limit=48)
    aliases = {
        "summary": "session_summary",
        "trigger": "recurring_trigger",
        "support": "support_strategy",
        "safety": "safety_summary",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in ALL_MEMORY_TYPES else "session_summary"


def _coerce_audience(value: object, *, fallback: str = "all") -> SafetyAudience:
    raw = _clean_text(value or fallback, limit=16).lower()
    if raw in {"teen", "minor", "youth"}:
        return SafetyAudience.teen
    if raw in {"adult", "grownup"}:
        return SafetyAudience.adult
    return SafetyAudience.all


def _event_dict(event: ToolExecutionEvent | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(event, ToolExecutionEvent):
        return asdict(event)
    return dict(event)


def _safe_preview(value: object, *, max_chars: int = 280) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _clean_text(value, limit=max_chars)
    if isinstance(value, list | tuple):
        return [_safe_preview(item, max_chars=max_chars) for item in list(value)[:MAX_TOOL_PREVIEWS]]
    if isinstance(value, dict):
        return {
            str(key): _safe_preview(item, max_chars=max_chars)
            for key, item in list(value.items())[:12]
            if str(key) not in {"content", "raw_result", "result"}
        }
    return _clean_text(value, limit=max_chars)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    allowed_risk_levels: frozenset[str] = ALL_RISK_LEVELS
    enabled_by_default: bool = True

    def to_deepseek_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolGate:
    risk_level: str = "L0"
    memory_mode: str = "summary_only"
    knowledge_enabled: bool = False
    tool_gate_mode: str = "normal_context"

    def allowed_tool_names(self) -> list[str]:
        if self.tool_gate_mode == "blocked_context":
            return [name for name in ["get_current_time", "summarize_session"] if self.allows(name)]
        if self.tool_gate_mode == "safety_context" or self.risk_level in HIGH_RISK_LEVELS:
            return [
                name
                for name in ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"]
                if self.allows(name)
            ]
        names = []
        if self.memory_mode != "off":
            names.extend(["search_memories", "save_memory_summary"])
        names.append("get_safety_resources")
        names.append("web_search")
        names.append("get_current_time")
        names.append("get_weather")
        names.append("summarize_session")
        if self.knowledge_enabled:
            names.append("ask_knowledge")
        return [name for name in names if self.allows(name)]

    def blocked_tool_names(self) -> list[str]:
        allowed = set(self.allowed_tool_names())
        return [
            spec.name
            for spec in TOOL_SPECS
            if spec.enabled_by_default and spec.name not in allowed
        ]

    def allows(self, name: str) -> bool:
        spec = TOOL_SPEC_BY_NAME.get(name)
        if spec is None:
            return False
        if name == "ask_knowledge" and not self.knowledge_enabled:
            return False
        if not spec.enabled_by_default and name != "ask_knowledge":
            return False
        if self.risk_level not in spec.allowed_risk_levels:
            return False
        if self.tool_gate_mode == "blocked_context":
            return name in BLOCKED_CONTEXT_TOOL_NAMES
        if self.tool_gate_mode == "safety_context" or self.risk_level in HIGH_RISK_LEVELS:
            return name in SAFETY_CONTEXT_TOOL_NAMES
        if name == "summarize_session":
            return True
        if self.memory_mode == "off":
            return name in (SAFETY_TOOL_NAMES | {"get_current_time"})
        return name in (MEMORY_TOOL_NAMES | SAFETY_TOOL_NAMES | {"web_search", "get_current_time", "get_weather"} | ({"ask_knowledge"} if self.knowledge_enabled else set()))


@dataclass
class ToolAuditCapture:
    previews: list[dict[str, Any]] = field(default_factory=list)
    memory_patch: dict[str, Any] = field(default_factory=dict)

    def record_preview(self, name: str, *, status: str, preview: object = None, error: str | None = None) -> None:
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if preview not in (None, "", [], {}):
            entry["preview"] = _safe_preview(preview)
        if error:
            entry["error"] = _clean_text(error, limit=80)
        self.previews.append(entry)


@dataclass
class DialogueToolPlan:
    tools: list[dict[str, Any]]
    tool_handlers: dict[str, ToolHandler]
    allowed_tool_names: list[str]
    blocked_tool_names: list[str]
    prompt_hint: str
    audit_capture: ToolAuditCapture


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="search_memories",
        description="Search the available user-visible memory index and return concise memory references.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A short phrase describing what memory context is needed.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Maximum number of memory references to return.",
                },
                "memory_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(VISIBLE_MEMORY_TYPES),
                    },
                    "description": "Optional visible memory types to search.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="save_memory_summary",
        description="Produce a safe session summary and candidate memories for the background memory pipeline.",
        allowed_risk_levels=LOW_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "session_summary": {
                    "type": "string",
                    "description": "A concise, non-sensitive summary of the current turn.",
                },
                "memory_candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "memory_type": {
                                "type": "string",
                                "enum": sorted(ALL_MEMORY_TYPES),
                            },
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "content": {"type": "string"},
                            "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "visibility": {"type": "string", "enum": ["user_visible", "internal_safety"]},
                            "structured_value": {
                                "type": "object",
                                "description": "Optional structured metadata for goal-type memories (e.g. goal_status, goal_category, completed_at).",
                            },
                        },
                        "required": ["content"],
                        "additionalProperties": False,
                    },
                    "description": "Optional candidate memories. Keep each item short and safe.",
                },
            },
            "required": ["session_summary"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_safety_resources",
        description="Return minimal safety support resources by region and teen/adult audience.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Short region code or location hint, for example CN or US.",
                },
                "audience": {
                    "type": "string",
                    "enum": ["all", "teen", "adult"],
                    "description": "Use teen for minors, adult for adults, all if unknown.",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="ask_knowledge",
        description="Placeholder for future curated knowledge lookup. Disabled in v1.",
        allowed_risk_levels=LOW_RISK_LEVELS,
        enabled_by_default=False,
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "use_my_context": {"type": "boolean"},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="web_search",
        description="Search the web for real-time facts, current events, and information beyond your knowledge cutoff, including psychological support resources and professional mental health information.",
        allowed_risk_levels=LOW_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords for finding current information on the web.",
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
    ToolSpec(
        name="safe_web_search",
        description="Search only trusted public support resources without including user personal details or unsafe method terms.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Short region code or location hint, for example CN or US.",
                },
                "audience": {
                    "type": "string",
                    "enum": ["all", "teen", "adult"],
                    "description": "Use teen for minors, adult for adults, all if unknown.",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_current_time",
        description="Get the current date, time, timezone, weekday, and how long the session has been running.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_weather",
        description="Get current weather for a city. Use when the user's mood may be influenced by weather, or when weather context is helpful.",
        allowed_risk_levels=LOW_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. 'Beijing', 'Shanghai', 'Chengdu'.",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="summarize_session",
        description="Summarize the current conversation session for the user. "
                    "Returns an overview, key topics, mood indicators, and suggestions "
                    "that have already been discussed. Read-only, no side effects.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["brief", "detailed", "themes_only", "progress"],
                    "description": "brief: short overview; detailed: full summary with themes/mood/suggestions; "
                                   "themes_only: core themes only; progress: changes compared to earlier turns.",
                },
            },
            "additionalProperties": False,
        },
    ),
)
TOOL_SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def _memory_entry_score(entry: dict[str, Any], query: str) -> float:
    text = " ".join(
        str(entry.get(key) or "")
        for key in ("title", "summary", "description", "search_text", "memory_type")
    ).lower()
    query_text = query.lower()
    if not query_text:
        lexical = 0.0
    elif query_text in text:
        lexical = 1.0
    else:
        query_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query_text))
        text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", text))
        lexical = len(query_terms & text_terms) / max(len(query_terms), 1)

    importance = _clamp_int(entry.get("importance"), default=3, minimum=1, maximum=5) / 5
    existing_score = float(entry.get("score") or 0.0)
    return round(max(existing_score, lexical * 0.72 + importance * 0.18), 4)


def _memory_entries_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    raw_items = list(state.get("memory_index") or []) + list(state.get("retrieved_memories") or [])
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        visibility = str(raw.get("visibility") or "user_visible")
        if visibility not in {"user_visible", "internal_safety"}:
            continue
        memory_id = _clean_text(raw.get("memory_id") or raw.get("id"), limit=80)
        if not memory_id:
            continue
        description = _clean_text(
            raw.get("description") or raw.get("summary") or raw.get("content"),
            limit=220,
        )
        if not description:
            continue
        entry = by_id.get(memory_id, {})
        merged = {
            **entry,
            "memory_id": memory_id,
            "memory_type": _normalize_memory_type(raw.get("memory_type")),
            "title": _clean_text(raw.get("title"), limit=80) or entry.get("title", ""),
            "summary": description or entry.get("summary", ""),
            "importance": raw.get("importance", entry.get("importance", 3)),
            "updated_at": raw.get("updated_at", entry.get("updated_at", "")),
            "freshness_warning": _clean_text(raw.get("freshness_warning"), limit=120),
            "why_selected": _clean_text(raw.get("why_selected"), limit=120),
            "visibility": visibility,
            "source": "memory_index",
            "search_text": _clean_text(raw.get("content") or description, limit=320),
        }
        if raw.get("score") is not None:
            merged["score"] = float(raw.get("score") or 0.0)
        by_id[memory_id] = merged
    return list(by_id.values())


def _search_memory_entries(
    state: Mapping[str, Any],
    *,
    query: str,
    limit: int,
    memory_types: set[str] | None = None,
    safety_context: bool = False,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for entry in _memory_entries_from_state(state):
        visibility = str(entry.get("visibility") or "user_visible")
        if safety_context and str(entry.get("memory_type") or "") not in SAFETY_CONTEXT_MEMORY_TYPES:
            continue
        if safety_context and visibility not in {"user_visible", "internal_safety"}:
            continue
        if not safety_context and visibility != "user_visible":
            continue
        if memory_types is not None and entry["memory_type"] not in memory_types:
            continue
        score = _memory_entry_score(entry, query)
        scored.append((score, str(entry.get("updated_at") or ""), entry))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    items: list[dict[str, Any]] = []
    for score, _, entry in scored[:limit]:
        items.append(
            {
                "memory_id": entry["memory_id"],
                "memory_type": entry["memory_type"],
                "title": entry.get("title") or entry["memory_type"],
                "summary": entry.get("summary", ""),
                "score": score,
                "why_selected": entry.get("why_selected", "") or "visible_memory_index",
                "freshness_warning": entry.get("freshness_warning", ""),
                "source": entry.get("source", "memory_index"),
            }
        )
    return items


def _normalize_memory_candidate(
    raw: Mapping[str, Any],
    *,
    risk_level: str,
) -> dict[str, Any] | None:
    memory_type = _normalize_memory_type(raw.get("memory_type"))
    content = _clean_text(raw.get("content") or raw.get("summary"), limit=1200)
    if not content:
        return None
    summary = _clean_text(raw.get("summary"), limit=260) or _clean_text(content, limit=180)
    title = _clean_text(raw.get("title"), limit=120) or summary[:40] or memory_type
    importance = _clamp_int(raw.get("importance"), default=3, minimum=1, maximum=5)
    visibility = "internal_safety" if memory_type == "safety_summary" or risk_level in HIGH_RISK_LEVELS else "user_visible"
    if _clean_text(raw.get("visibility"), limit=24) == "internal_safety":
        visibility = "internal_safety"
    normalized: dict[str, Any] = {
        "memory_type": memory_type,
        "title": title,
        "summary": summary,
        "content": content,
        "importance": importance,
        "tags": _unique_strings(raw.get("tags")),
        "visibility": visibility,
    }
    # Pass through structured_value for goal-type memories
    if isinstance(raw.get("structured_value"), dict):
        normalized["structured_value"] = dict(raw["structured_value"])
    return normalized


def _build_search_memories_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def search_memories(arguments: dict[str, Any]) -> dict[str, Any]:
        query = _clean_text(arguments.get("query"), limit=240)
        limit = _clamp_int(arguments.get("limit"), default=3, minimum=1, maximum=5)
        safety_context = str(state.get("tool_gate_mode") or "") == "safety_context" or str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS
        raw_types = arguments.get("memory_types")
        memory_types = None
        if isinstance(raw_types, list | tuple):
            memory_types = {
                _normalize_memory_type(item)
                for item in raw_types
                if _normalize_memory_type(item) in (SAFETY_CONTEXT_MEMORY_TYPES if safety_context else VISIBLE_MEMORY_TYPES)
            } or None
        items = _search_memory_entries(
            state,
            query=query,
            limit=limit,
            memory_types=memory_types,
            safety_context=safety_context,
        )
        capture.record_preview(
            "search_memories",
            status="completed",
            preview=[
                {"memory_id": item["memory_id"], "title": item["title"], "score": item["score"]}
                for item in items[:3]
            ],
        )
        return {
            "query": query,
            "count": len(items),
            "items": items,
        }

    return search_memories


def _build_save_memory_summary_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def save_memory_summary(arguments: dict[str, Any]) -> dict[str, Any]:
        risk_level = str(state.get("risk_level") or "L0")
        summary = _clean_text(arguments.get("session_summary") or arguments.get("summary"), limit=1000)
        raw_candidates = arguments.get("memory_candidates")
        normalized_candidates: list[dict[str, Any]] = []
        if isinstance(raw_candidates, list | tuple):
            for raw in raw_candidates[:4]:
                if not isinstance(raw, dict):
                    continue
                candidate = _normalize_memory_candidate(raw, risk_level=risk_level)
                if candidate is not None:
                    normalized_candidates.append(candidate)
        if summary and not normalized_candidates:
            normalized_candidates.append(
                {
                    "memory_type": "session_summary",
                    "title": "Turn summary",
                    "summary": _clean_text(summary, limit=260),
                    "content": summary,
                    "importance": 3,
                    "tags": ["summary"],
                    "visibility": "user_visible",
                }
            )
        memory_patch = {
            "session_summary": summary,
            "memory_candidates": normalized_candidates,
            "memory_policy": "write_safe_summary",
            "memory_policy_reason": "tool_save_memory_summary",
            "should_write_memory": bool(summary or normalized_candidates),
        }
        capture.memory_patch = memory_patch
        capture.record_preview(
            "save_memory_summary",
            status="completed",
            preview={
                "session_summary_chars": len(summary),
                "candidate_count": len(normalized_candidates),
                "candidate_types": [candidate["memory_type"] for candidate in normalized_candidates[:3]],
            },
        )
        return memory_patch

    return save_memory_summary


def _build_get_safety_resources_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def get_safety_resources(arguments: dict[str, Any]) -> dict[str, Any]:
        profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
        default_audience = str(profile.get("user_mode") or state.get("user_mode") or "all")
        region = _clean_text(arguments.get("region") or state.get("crisis_resource_region") or "CN", limit=24) or "CN"
        audience = _coerce_audience(arguments.get("audience"), fallback=default_audience)
        response = build_safety_resources(region=region, audience=audience)
        payload = response.model_dump(mode="json")
        capture.record_preview(
            "get_safety_resources",
            status="completed",
            preview=[
                {"resource_type": item.get("resource_type"), "title": item.get("title")}
                for item in payload.get("items", [])[:3]
                if isinstance(item, dict)
            ],
        )
        return payload

    return get_safety_resources


def _build_web_search_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def web_search_tool(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.services.search_service import search_web  # lazy import to avoid circular dependency

        query = _clean_text(arguments.get("query"), limit=240)
        max_results = _clamp_int(arguments.get("max_results"), default=3, minimum=1, maximum=5)
        results, error = search_web(query, max_results=max_results)
        status = "completed" if error is None else "error"
        error_text = None
        if error:
            error_text = f"search_failed: {error}"
        items: list[dict[str, Any]] = []
        for result in results:
            items.append({
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
                "score": result.score,
            })
        capture.record_preview(
            "web_search",
            status=status,
            preview=[
                {"title": result.title, "url": result.url}
                for result in results[:3]
            ],
            error=error_text,
        )
        output: dict[str, Any] = {
            "query": query,
            "count": len(items),
            "items": items,
            "status": status,
        }
        if error:
            output["error"] = error
        logger.debug(
            "web_search tool completed status=%s result_count=%d error=%s query_chars=%d",
            status,
            len(items),
            error or "",
            len(query),
        )
        return output

    return web_search_tool


def _build_safe_web_search_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def safe_web_search(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.services.search_service import search_web  # lazy import to avoid circular dependency

        profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
        default_audience = "teen" if str(profile.get("user_mode") or state.get("user_mode") or "") == "teen" else "all"
        region = _clean_text(arguments.get("region") or state.get("crisis_resource_region") or "CN", limit=24) or "CN"
        audience = _coerce_audience(arguments.get("audience"), fallback=default_audience)
        query = f"{region} mental health crisis support resources {audience.value}"
        results, error = search_web(query, max_results=3)
        status = "completed" if error is None else "error"
        items = [
            {
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
                "score": result.score,
            }
            for result in results
        ]
        capture.record_preview(
            "safe_web_search",
            status=status,
            preview={"query": query, "count": len(items)},
            error=f"search_failed: {error}" if error else None,
        )
        output: dict[str, Any] = {
            "query": query,
            "count": len(items),
            "items": items,
            "status": status,
        }
        if error:
            output["error"] = error
        return output

    return safe_web_search


def _build_get_current_time_handler(capture: ToolAuditCapture) -> ToolHandler:
    _session_start: datetime | None = None

    def get_current_time(_arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal _session_start
        now = datetime.now(timezone.utc)
        if _session_start is None:
            _session_start = now
            elapsed = 0.0
        else:
            elapsed = (now - _session_start).total_seconds()
        result = build_temporal_context(now=now)
        result["session_elapsed_seconds"] = round(elapsed, 1)
        capture.record_preview(
            "get_current_time",
            status="completed",
            preview={"local_iso": result["local_iso"], "weekday": result["weekday"]},
        )
        return result

    return get_current_time


def _build_get_weather_handler(capture: ToolAuditCapture) -> ToolHandler:
    def get_weather_tool(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.services.weather_service import get_weather  # lazy import

        city = _clean_text(arguments.get("city") or "", limit=40) or "Beijing"
        text, error = get_weather(city)
        status = "completed" if error is None else "error"
        if error:
            capture.record_preview("get_weather", status="error", error=f"weather_failed: {error}")
            return {"city": city, "weather": "", "error": error}
        capture.record_preview("get_weather", status="completed", preview={"city": city, "weather": text})
        return {"city": city, "weather": text}

    return get_weather_tool


_SUGGESTION_PATTERNS = [
    re.compile(r"建议\S{0,2}(.+?)(?:[。；！？\n]|$)"),
    re.compile(r"可以试试(.+?)(?:[。；！？\n]|$)"),
    re.compile(r"不妨(.+?)(?:[。；！？\n]|$)"),
]
_STOP_WORDS = frozenset({"的", "了", "是", "在", "我", "你", "他", "她", "它", "们", "这", "那",
                          "和", "与", "或", "就", "也", "都", "要", "会", "能", "不", "很", "吗",
                          "呢", "吧", "啊", "哦", "嗯", "还", "有", "没", "但", "只", "个", "对",
                          "上", "下", "中", "了", "着", "过"})


def _extract_suggestions(assistant_messages: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    for msg in assistant_messages:
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        for pattern in _SUGGESTION_PATTERNS:
            for match in pattern.finditer(content):
                text = match.group(1).strip()
                if len(text) >= 3 and len(text) <= 60:
                    suggestions.append(text)
    return list(dict.fromkeys(suggestions))


def _extract_topics(
    recent_messages: list[dict[str, Any]],
    last_summary: str,
    session_summary: str,
) -> list[str]:
    user_texts: list[str] = []
    for msg in recent_messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            user_texts.append(content)
    combined = " ".join(user_texts)
    chars: list[str] = []
    for ch in combined:
        if "\u4e00" <= ch <= "\u9fff":
            chars.append(ch)
        elif chars and chars[-1] != " ":
            chars.append(" ")
    text = "".join(chars)
    words: list[str] = []
    i = 0
    while i + 1 < len(text):
        if text[i] == " ":
            i += 1
            continue
        for wl in (4, 3, 2):
            end = i + wl
            if end <= len(text):
                w = text[i:end].strip()
                if len(w) >= 2 and " " not in w:
                    words.append(w)
                    break
        i += 1
    freq: dict[str, int] = {}
    for w in words:
        if w not in _STOP_WORDS:
            freq[w] = freq.get(w, 0) + 1
    for summary_words in [last_summary, session_summary]:
        for ch in summary_words:
            if "\u4e00" <= ch <= "\u9fff":
                for wl in (4, 3, 2):
                    idx = summary_words.find(ch)
                    if idx + wl <= len(summary_words):
                        w = summary_words[idx:idx + wl]
                        if w not in _STOP_WORDS and len(w) >= 2:
                            freq[w] = freq.get(w, 0) + 2
    sorted_topics = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [topic for topic, _ in sorted_topics[:6]]


def _extract_mood_indicators(recent_messages: list[dict[str, Any]]) -> list[str]:
    mood_keywords = ["焦虑", "紧张", "担心", "害怕", "恐惧", "难过", "悲伤", "沮丧",
                     "生气", "愤怒", "烦躁", "疲惫", "累", "无力", "无助", "绝望",
                     "平静", "放松", "开心", "高兴", "期待", "感激", "希望"]
    all_text = " ".join(
        msg.get("content", "") or ""
        for msg in recent_messages
        if msg.get("role") == "user"
    )
    found: list[str] = []
    for kw in mood_keywords:
        if kw in all_text:
            found.append(kw)
    return list(dict.fromkeys(found))


def _build_summarize_session_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def summarize_session(arguments: dict[str, Any]) -> dict[str, Any]:
        fmt = _clean_text(arguments.get("format"), limit=16) or "brief"
        if fmt not in ("brief", "detailed", "themes_only", "progress"):
            fmt = "brief"

        recent_messages = state.get("recent_messages")
        if not isinstance(recent_messages, list):
            recent_messages = []
        turn_count = sum(1 for msg in recent_messages if isinstance(msg, dict) and msg.get("role") == "user")
        last_summary = str(state.get("last_summary") or "")
        session_summary = str(state.get("session_summary") or "")

        topics = _extract_topics(recent_messages, last_summary, session_summary)

        if fmt == "themes_only":
            result: dict[str, Any] = {
                "format": "themes_only",
                "themes": topics,
                "source": "conversation_state",
            }
            capture.record_preview("summarize_session", status="completed", preview={"format": fmt, "theme_count": len(topics)})
            return result

        user_messages = [msg for msg in recent_messages if isinstance(msg, dict) and msg.get("role") == "user"]
        assistant_messages = [msg for msg in recent_messages if isinstance(msg, dict) and msg.get("role") == "assistant"]
        current_turn_topic = user_messages[-1].get("content", "")[:80] if user_messages else ""

        if fmt == "brief":
            overview_parts: list[str] = []
            if session_summary:
                overview_parts.append(session_summary)
            elif last_summary:
                overview_parts.append(last_summary)
            overview = ". ".join(overview_parts) if overview_parts else ""
            result = {
                "format": "brief",
                "overview": overview,
                "topics": topics,
                "theme_count": len(topics),
                "turn_count": turn_count,
                "current_turn_topic": current_turn_topic,
                "source": "conversation_state",
            }
            capture.record_preview("summarize_session", status="completed", preview={"format": fmt, "theme_count": len(topics), "turn_count": turn_count})
            return result

        if fmt == "detailed":
            suggestions = _extract_suggestions(assistant_messages)
            mood = _extract_mood_indicators(recent_messages)
            overview_parts = []
            if session_summary:
                overview_parts.append(session_summary)
            elif last_summary:
                overview_parts.append(last_summary)
            overview = ". ".join(overview_parts) if overview_parts else ""
            result = {
                "format": "detailed",
                "overview": overview,
                "topics": topics,
                "theme_count": len(topics),
                "turn_count": turn_count,
                "current_turn_topic": current_turn_topic,
                "suggestions_given": suggestions,
                "mood_indicators": mood,
                "source": "conversation_state",
            }
            capture.record_preview("summarize_session", status="completed", preview={"format": fmt, "theme_count": len(topics), "turn_count": turn_count, "mood_count": len(mood)})
            return result

        # progress
        suggestions = _extract_suggestions(assistant_messages)
        mood = _extract_mood_indicators(recent_messages)
        result = {
            "format": "progress",
            "topics": topics,
            "topic_changes": [],
            "ongoing_themes": topics,
            "turn_count": turn_count,
            "source": "conversation_state",
        }
        capture.record_preview("summarize_session", status="completed", preview={"format": fmt, "theme_count": len(topics), "turn_count": turn_count})
        return result

    return summarize_session


def _tool_prompt_hint(tool_names: list[str]) -> str:
    if not tool_names:
        return ""
    descriptions = {
        "search_memories": "search_memories: search only the available user-visible memory index; return references, not raw private content.",
        "save_memory_summary": "save_memory_summary: produce safe summaries/candidate memories for the backend memory pipeline; it does not write directly.",
        "get_safety_resources": "get_safety_resources: return minimal safety resources by region/audience when real-world support is relevant.",
        "web_search": "web_search: search the web for real-time facts, current events, and information beyond your knowledge; return title, url, and snippet.",
        "safe_web_search": "safe_web_search: search trusted public support resources using backend-generated queries; never include user personal details or unsafe method terms.",
        "get_current_time": "get_current_time: return current UTC/local time, weekday, timezone, and session elapsed seconds.",
        "get_weather": "get_weather: get current weather for a city via wttr.in; use sparingly, only when weather context helps understand user's mood or situation.",
        "summarize_session": "summarize_session: summarize the current conversation for the user on request; read-only.",
    }
    lines = [
        "",
        "[Tool policy]",
        "Use tools only when they materially improve this turn. Do not call tools that are not listed.",
        "IMPORTANT: When a user asks about real-world facts, news, current events, historical dates, or any verifiable information you are not certain about, you MUST call web_search. Do NOT rely on memory or training data for time-sensitive or factual claims.",
    ]
    lines.extend(f"- {descriptions[name]}" for name in tool_names if name in descriptions)
    if "web_search" in tool_names:
        lines.append("- web_search: Use for real-time facts, current events, professional resources, or any information beyond your knowledge cutoff. Do NOT include any user personal information in the search query.")
    lines.append("Never claim a memory was permanently saved; the backend reviews candidates asynchronously.")
    lines.append("Never say you have 'checked', 'searched', 'looked up', or 'queried' something unless you actually called the corresponding tool. Making up search actions is dishonest and harmful.")
    return "\n".join(lines)


def build_dialogue_tool_plan(
    state: Mapping[str, Any],
    *,
    knowledge_enabled: bool = False,
) -> DialogueToolPlan:
    tooling_enabled = state.get("tooling_enabled")
    if tooling_enabled is not True:
        logger.debug("Dialogue tooling disabled tooling_enabled=%s", tooling_enabled)
        return DialogueToolPlan(
            tools=[],
            tool_handlers={},
            allowed_tool_names=[],
            blocked_tool_names=[],
            prompt_hint="",
            audit_capture=ToolAuditCapture(),
        )
    gate = ToolGate(
        risk_level=str(state.get("risk_level") or "L0"),
        memory_mode=str(state.get("memory_mode") or "summary_only"),
        knowledge_enabled=knowledge_enabled,
        tool_gate_mode=str(state.get("tool_gate_mode") or "normal_context"),
    )
    allowed_names = gate.allowed_tool_names()
    capture = ToolAuditCapture()
    handlers: dict[str, ToolHandler] = {}
    if "search_memories" in allowed_names:
        handlers["search_memories"] = _build_search_memories_handler(state, capture)
    if "save_memory_summary" in allowed_names:
        handlers["save_memory_summary"] = _build_save_memory_summary_handler(state, capture)
    if "get_safety_resources" in allowed_names:
        handlers["get_safety_resources"] = _build_get_safety_resources_handler(state, capture)
    if "web_search" in allowed_names:
        handlers["web_search"] = _build_web_search_handler(state, capture)
    if "safe_web_search" in allowed_names:
        handlers["safe_web_search"] = _build_safe_web_search_handler(state, capture)
    if "get_current_time" in allowed_names:
        handlers["get_current_time"] = _build_get_current_time_handler(capture)
    if "get_weather" in allowed_names:
        handlers["get_weather"] = _build_get_weather_handler(capture)
    if "summarize_session" in allowed_names:
        handlers["summarize_session"] = _build_summarize_session_handler(state, capture)

    specs = [TOOL_SPEC_BY_NAME[name] for name in allowed_names if name in TOOL_SPEC_BY_NAME]
    blocked_names = gate.blocked_tool_names()
    logger.debug(
        "Dialogue tool plan built risk_level=%s memory_mode=%s gate_mode=%s allowed=%s blocked=%s",
        gate.risk_level,
        gate.memory_mode,
        gate.tool_gate_mode,
        allowed_names,
        blocked_names,
    )
    return DialogueToolPlan(
        tools=[spec.to_deepseek_tool() for spec in specs],
        tool_handlers=handlers,
        allowed_tool_names=allowed_names,
        blocked_tool_names=blocked_names,
        prompt_hint=_tool_prompt_hint(allowed_names),
        audit_capture=capture,
    )


def summarize_tool_events(
    tool_events: object,
    *,
    previews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_events = tool_events if isinstance(tool_events, list | tuple) else []
    events = [
        _event_dict(event)
        for event in raw_events
        if isinstance(event, ToolExecutionEvent) or isinstance(event, Mapping)
    ]
    names = [str(event.get("name") or "") for event in events if str(event.get("name") or "")]
    status_counts = Counter(str(event.get("status") or "unknown") for event in events)
    errors = [
        {
            "name": str(event.get("name") or ""),
            "error": _clean_text(event.get("error"), limit=80),
        }
        for event in events
        if event.get("error")
    ]
    summary: dict[str, Any] = {
        "tool_count": len(events),
        "tool_names": list(dict.fromkeys(names))[:MAX_TOOL_PREVIEWS],
        "status_counts": dict(status_counts),
        "error_count": len(errors),
    }
    if errors:
        summary["errors"] = errors[:MAX_TOOL_PREVIEWS]
    if previews:
        summary["previews"] = [_safe_preview(preview) for preview in previews[:MAX_TOOL_PREVIEWS]]
    return summary


def _current_turn_text(state: Mapping[str, Any], user_prompt: str) -> str:
    return _clean_text(
        state.get("normalized_text") or state.get("user_text") or user_prompt,
        limit=180,
    )


def _prefetch_search_query(text: str) -> str:
    cleaned = _clean_text(text, limit=160)
    if not cleaned:
        return ""
    current_year = str(datetime.now().year)
    if any(term in cleaned for term in ("去世", "逝世", "死亡")) and any(
        term in cleaned for term in ("时间", "什么时候", "哪天", "日期", "最新")
    ):
        return f"{cleaned} 最新 {current_year} 讣告"
    for action in ("访华", "访中"):
        if action not in cleaned:
            continue
        subject = re.split(rf"{action}|是什么|什么时候|哪天|日期|时间|[？?，,。；;：:\s]+", cleaned, maxsplit=1)[0]
        subject = _clean_text(subject, limit=40)
        if subject:
            return f"{subject} {action} {current_year} 国事访问 外交部"
        return f"{cleaned} {current_year} 国事访问 外交部"
    return cleaned


def _should_prefetch_web_search(state: Mapping[str, Any], user_prompt: str, plan: DialogueToolPlan) -> bool:
    if "web_search" not in plan.tool_handlers:
        return False
    text = _current_turn_text(state, user_prompt)
    return bool(text and CURRENT_FACT_QUERY_RE.search(text))


def _format_prefetched_web_context(query: str, output: Mapping[str, Any]) -> str:
    status = _clean_text(output.get("status"), limit=40) or "unknown"
    error = _clean_text(output.get("error"), limit=80)
    items = output.get("items") if isinstance(output.get("items"), list) else []
    lines = [
        "",
        "[Pre-fetched web_search result]",
        f"Query: {query}",
        f"Status: {status}",
        "Use this web context for current or factual claims. Extract concrete dates and facts present in snippets; prefer named sources in snippets. If it is empty or errored, say what could not be verified.",
    ]
    if error:
        lines.append(f"Error: {error}")
    for index, raw_item in enumerate(items[:5], start=1):
        item = raw_item if isinstance(raw_item, Mapping) else {}
        title = _clean_text(item.get("title"), limit=120)
        url = _clean_text(item.get("url"), limit=220)
        snippet = _clean_text(item.get("snippet"), limit=360)
        lines.extend(
            [
                f"[{index}] {title}",
                f"URL: {url}",
                f"Snippet: {snippet}",
            ]
        )
    lines.append("[/Pre-fetched web_search result]")
    return "\n".join(lines)


def _prefetch_web_search_for_turn(
    state: Mapping[str, Any],
    user_prompt: str,
    plan: DialogueToolPlan,
) -> tuple[list[ToolExecutionEvent], str, Mapping[str, Any]]:
    query = _prefetch_search_query(_current_turn_text(state, user_prompt))
    if not query:
        return [], "", {}
    arguments = {"query": query, "max_results": 5}
    handler = plan.tool_handlers.get("web_search")
    if handler is None:
        return [], "", {}

    try:
        output = handler(arguments)
        if not isinstance(output, Mapping):
            output = {"status": "error", "error": "invalid_tool_output", "items": []}
    except Exception as exc:
        logger.warning("Prefetched web_search failed: %s", exc)
        output = {"status": "error", "error": "handler_error", "items": []}

    status = "completed" if output.get("status") == "completed" else "error"
    event = ToolExecutionEvent(
        tool_call_id="prefetch-web-search",
        name="web_search",
        arguments=arguments,
        status=status,
        error=_clean_text(output.get("error"), limit=80) or None,
    )
    return [event], _format_prefetched_web_context(query, output), output


def _best_prefetched_web_item(output: Mapping[str, Any]) -> tuple[str, str, str] | None:
    items = output.get("items") if isinstance(output.get("items"), list) else []
    candidates: list[tuple[int, str, str, str]] = []
    for raw_item in items:
        item = raw_item if isinstance(raw_item, Mapping) else {}
        title = _clean_text(item.get("title"), limit=120)
        url = _clean_text(item.get("url"), limit=220)
        snippet = _clean_text(item.get("snippet"), limit=500)
        if not snippet:
            continue
        sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(snippet) if part.strip()]
        if not sentences:
            sentences = [snippet]
        for sentence in sentences:
            score = len(FACT_DATE_RE.findall(sentence)) * 5
            score += 2 if title and title in sentence else 0
            score += min(len(sentence), 180) // 60
            candidates.append((score, sentence, title, url))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _score, sentence, title, url = candidates[0]
    return sentence, title, url


def _clean_prefetched_fact_sentence(sentence: str, query: str) -> str:
    cleaned = _clean_text(sentence, limit=500)
    if not cleaned:
        return ""
    cleaned = re.sub(r"(\d{4})\s+年\s*", r"\1年", cleaned)
    cleaned = re.sub(r"(\d{1,2})\s+月\s*", r"\1月", cleaned)
    cleaned = re.sub(r"(\d{1,2})\s+日", r"\1日", cleaned)
    cleaned = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", cleaned)
    cleaned = re.sub(r"\s+([，,。；;：:])", r"\1", cleaned)
    markers = ["根据", "新华社"]
    for action in ("去世", "逝世", "死亡", "访华", "访中", "访美"):
        if action not in query:
            continue
        subject = query.split(action, 1)[0].strip()
        if len(subject) >= 2:
            markers.append(subject)
        markers.append(action)
    starts = [cleaned.find(marker) for marker in markers if marker and cleaned.find(marker) > 0]
    if starts:
        cleaned = cleaned[min(starts):].lstrip("，,。；;：: ")
    return cleaned


def _fallback_answer_from_prefetched_web(query: str, output: Mapping[str, Any]) -> str:
    if int(output.get("count") or 0) <= 0:
        return ""
    best = _best_prefetched_web_item(output)
    if best is None:
        return ""
    sentence, title, url = best
    sentence = _clean_prefetched_fact_sentence(sentence, query)
    if not sentence:
        return ""
    source = f"\n\n来源：{title}".strip() if title else ""
    return f"我查到的搜索结果显示：{sentence}{source}"


def _should_prefer_prefetched_fact(assistant_text: str, fallback_answer: str) -> bool:
    if not fallback_answer:
        return False
    if not assistant_text.strip():
        return True
    if not FACT_DATE_RE.search(fallback_answer):
        return False
    if not FACT_DATE_RE.search(assistant_text):
        return True
    fallback_dates = set(FACT_DATE_RE.findall(fallback_answer))
    assistant_dates = set(FACT_DATE_RE.findall(assistant_text))
    if fallback_dates and assistant_dates and not (fallback_dates & assistant_dates):
        return True
    contradiction_markers = ("还健在", "没有去世", "没查到", "没有查到", "没有找到", "没有确认", "未确认")
    return any(marker in assistant_text for marker in contradiction_markers)


def _parse_actions_reply(text: str | None) -> tuple[str, list[str]]:
    if not text:
        return "", []
    text = text.strip()
    if "---" not in text:
        return text, []
    body, actions_block = text.rsplit("---", 1)
    actions: list[str] = []
    for action in actions_block.strip().splitlines():
        item = action.strip().lstrip("0123456789.、 ").strip()
        if item:
            actions.append(item)
    return body.strip(), actions[:3]


async def run_dialogue_reply_with_tools(
    state: Mapping[str, Any],
    *,
    system_prompt: str,
    user_prompt: str,
    messages: list[dict[str, Any]] | None = None,
    tool_plan: DialogueToolPlan | None = None,
) -> dict[str, Any]:
    plan = tool_plan or build_dialogue_tool_plan(state)
    if not plan.tools:
        return {
            "assistant_text": "",
            "suggested_actions": [],
            "tool_events": [],
            "tool_trace_summary": summarize_tool_events([]),
        }
    system_content = system_prompt
    if plan.prompt_hint:
        system_content = f"{system_content}\n{plan.prompt_hint}"
    prefetched_events: list[ToolExecutionEvent] = []
    prefetched_output: Mapping[str, Any] = {}
    prefetched_query = ""
    if _should_prefetch_web_search(state, user_prompt, plan):
        prefetched_query = _prefetch_search_query(_current_turn_text(state, user_prompt))
        prefetched_events, prefetched_context, prefetched_output = _prefetch_web_search_for_turn(state, user_prompt, plan)
        if prefetched_context:
            system_content = f"{system_content}\n{prefetched_context}"
    reply_messages = messages or [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_prompt},
    ]
    if reply_messages:
        first_message = dict(reply_messages[0])
        first_message["content"] = system_content
        reply_messages = [first_message, *[dict(message) for message in reply_messages[1:]]]
    tool_result: ToolChatResult = await deepseek_client.chat_with_tools(
        reply_messages,
        tools=plan.tools,
        tool_handlers=plan.tool_handlers,
        tool_choice="auto",
        thinking_enabled=False,
        max_tokens=max(int(settings.deepseek_chat_max_tokens), DEFAULT_DIALOGUE_REPLY_MAX_TOKENS),
        max_tool_rounds=DEFAULT_MAX_TOOL_ROUNDS,
    )
    combined_tool_events = [*prefetched_events, *tool_result.tool_events]
    if not combined_tool_events:
        logger.debug("No tool calls were made by the model.")
    assistant_text, suggested_actions = _parse_actions_reply(tool_result.content)
    if prefetched_output:
        prefetched_answer = _fallback_answer_from_prefetched_web(prefetched_query, prefetched_output)
        if _should_prefer_prefetched_fact(assistant_text, prefetched_answer):
            assistant_text = prefetched_answer
    tool_events = [_event_dict(event) for event in combined_tool_events]
    tool_trace_summary = summarize_tool_events(combined_tool_events, previews=plan.audit_capture.previews)
    result: dict[str, Any] = {
        "assistant_text": assistant_text,
        "suggested_actions": suggested_actions,
        "tool_events": tool_events,
        "tool_trace_summary": tool_trace_summary,
    }
    if plan.audit_capture.memory_patch:
        result.update(plan.audit_capture.memory_patch)
    if not assistant_text.strip() and tool_result.finish_reason in {"request_failed", "max_tool_rounds_exceeded"}:
        result.update(
            {
                "delivery_status": "failed_no_reply",
                "failure_reason": tool_result.finish_reason,
                "retryable": tool_result.finish_reason == "request_failed",
            }
        )
    return result
