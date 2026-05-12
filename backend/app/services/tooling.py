from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from app.schemas.common import SafetyAudience
from app.services.deepseek_client import (
    DEFAULT_MAX_TOOL_ROUNDS,
    ToolChatResult,
    ToolExecutionEvent,
    ToolHandler,
    deepseek_client,
)
from app.services.safety_service import build_safety_resources


LOW_RISK_LEVELS = frozenset({"L0", "L1"})
HIGH_RISK_LEVELS = frozenset({"L2", "L3"})
ALL_RISK_LEVELS = LOW_RISK_LEVELS | HIGH_RISK_LEVELS
MEMORY_TOOL_NAMES = frozenset({"search_memories", "save_memory_summary"})
SAFETY_TOOL_NAMES = frozenset({"get_safety_resources"})
MAX_TOOL_PREVIEWS = 5

VISIBLE_MEMORY_TYPES = {
    "profile",
    "preference",
    "session_summary",
    "recurring_trigger",
    "support_strategy",
    "relationship",
    "state",
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

    def allowed_tool_names(self) -> list[str]:
        names = []
        high_risk = self.risk_level in HIGH_RISK_LEVELS
        if not high_risk and self.memory_mode != "off":
            names.extend(["search_memories", "save_memory_summary"])
        names.append("get_safety_resources")
        names.append("web_search")
        names.append("get_current_time")
        names.append("get_weather")
        if self.knowledge_enabled and not high_risk:
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
        if self.risk_level in HIGH_RISK_LEVELS:
            return name in (SAFETY_TOOL_NAMES | {"get_current_time"})
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
        allowed_risk_levels=LOW_RISK_LEVELS,
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
        if visibility != "user_visible":
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
) -> list[dict[str, Any]]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for entry in _memory_entries_from_state(state):
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
    return {
        "memory_type": memory_type,
        "title": title,
        "summary": summary,
        "content": content,
        "importance": importance,
        "tags": _unique_strings(raw.get("tags")),
        "visibility": visibility,
    }


def _build_search_memories_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def search_memories(arguments: dict[str, Any]) -> dict[str, Any]:
        query = _clean_text(arguments.get("query"), limit=240)
        limit = _clamp_int(arguments.get("limit"), default=3, minimum=1, maximum=5)
        raw_types = arguments.get("memory_types")
        memory_types = None
        if isinstance(raw_types, list | tuple):
            memory_types = {
                _normalize_memory_type(item)
                for item in raw_types
                if _normalize_memory_type(item) in VISIBLE_MEMORY_TYPES
            } or None
        items = _search_memory_entries(state, query=query, limit=limit, memory_types=memory_types)
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
        }
        if error:
            output["error"] = error
        return output

    return web_search_tool


def _build_get_current_time_handler(capture: ToolAuditCapture) -> ToolHandler:
    tz_cn = timezone(timedelta(hours=8))
    _WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    _session_start: datetime | None = None

    def get_current_time(_arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal _session_start
        now = datetime.now(timezone.utc)
        local = now.astimezone(tz_cn)
        if _session_start is None:
            _session_start = now
            elapsed = 0.0
        else:
            elapsed = (now - _session_start).total_seconds()
        result = {
            "utc_iso": now.isoformat(),
            "local_iso": local.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "Asia/Shanghai",
            "weekday": _WEEKDAY_NAMES[local.weekday()],
            "session_elapsed_seconds": round(elapsed, 1),
        }
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


def _tool_prompt_hint(tool_names: list[str]) -> str:
    if not tool_names:
        return ""
    descriptions = {
        "search_memories": "search_memories: search only the available user-visible memory index; return references, not raw private content.",
        "save_memory_summary": "save_memory_summary: produce safe summaries/candidate memories for the backend memory pipeline; it does not write directly.",
        "get_safety_resources": "get_safety_resources: return minimal safety resources by region/audience when real-world support is relevant.",
        "web_search": "web_search: search the web for real-time psychological support resources; return title, url, and snippet.",
        "get_current_time": "get_current_time: return current UTC/local time, weekday, timezone, and session elapsed seconds.",
        "get_weather": "get_weather: get current weather for a city via wttr.in; use sparingly, only when weather context helps understand user's mood or situation.",
    }
    lines = [
        "",
        "[Tool policy]",
        "Use tools only when they materially improve this turn. Do not call tools that are not listed.",
    ]
    lines.extend(f"- {descriptions[name]}" for name in tool_names if name in descriptions)
    if "web_search" in tool_names:
        lines.append("- web_search: Only search for psychological support resources or professional mental health information. Do NOT include any user personal information in the search query.")
    lines.append("Never claim a memory was permanently saved; the backend reviews candidates asynchronously.")
    return "\n".join(lines)


def build_dialogue_tool_plan(
    state: Mapping[str, Any],
    *,
    knowledge_enabled: bool = False,
) -> DialogueToolPlan:
    if state.get("tooling_enabled") is not True:
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
    if "get_current_time" in allowed_names:
        handlers["get_current_time"] = _build_get_current_time_handler(capture)
    if "get_weather" in allowed_names:
        handlers["get_weather"] = _build_get_weather_handler(capture)

    specs = [TOOL_SPEC_BY_NAME[name] for name in allowed_names if name in TOOL_SPEC_BY_NAME]
    return DialogueToolPlan(
        tools=[spec.to_deepseek_tool() for spec in specs],
        tool_handlers=handlers,
        allowed_tool_names=allowed_names,
        blocked_tool_names=gate.blocked_tool_names(),
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
    tool_result: ToolChatResult = await deepseek_client.chat_with_tools(
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ],
        tools=plan.tools,
        tool_handlers=plan.tool_handlers,
        tool_choice="auto",
        thinking_enabled=False,
        max_tool_rounds=DEFAULT_MAX_TOOL_ROUNDS,
    )
    assistant_text, suggested_actions = _parse_actions_reply(tool_result.content)
    tool_events = [_event_dict(event) for event in tool_result.tool_events]
    tool_trace_summary = summarize_tool_events(tool_result.tool_events, previews=plan.audit_capture.previews)
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
