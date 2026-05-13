from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from app.graphs.nodes.common import excerpt, last_user_message
from app.services.deepseek_client import deepseek_client


logger = logging.getLogger(__name__)

DIGEST_SCHEMA_VERSION = 1
DIGEST_TIMEOUT_SECONDS = 2.0
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 60
MAX_TEXT_CHARS = 160
MAX_SUMMARY_CHARS = 200

LIST_FIELDS = (
    "key_themes",
    "effective_interventions",
    "ineffective_interventions",
    "unresolved_threads",
    "significant_changes",
)
STRING_FIELDS = ("emotional_arc", "summary_200chars")
HIGH_RISK_DETAIL_TERMS = (
    "刀",
    "药",
    "跳楼",
    "楼顶",
    "绳",
    "煤气",
    "割腕",
    "安眠药",
    "pills",
    "knife",
    "roof",
    "bridge",
)


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _redact_sensitive(text: str, *, risk_level: str) -> str:
    redacted = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "[已过滤联系方式]",
        text,
    )
    redacted = re.sub(r"(?<!\d)\d[\d\s-]{6,}\d(?!\d)", "[已过滤联系方式]", redacted)
    if risk_level in {"L2", "L3"}:
        for term in HIGH_RISK_DETAIL_TERMS:
            redacted = re.sub(re.escape(term), "[已概括安全风险细节]", redacted, flags=re.IGNORECASE)
    return redacted


def _safe_text(value: object, *, limit: int, risk_level: str) -> str:
    text = _redact_sensitive(_compact(value), risk_level=risk_level)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _safe_list(value: object, *, fallback: object = None, risk_level: str) -> list[str]:
    raw_items = value if isinstance(value, list) else fallback
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []

    seen: set[str] = set()
    items: list[str] = []
    for raw_item in raw_items:
        item = _safe_text(raw_item, limit=MAX_ITEM_CHARS, risk_level=risk_level)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_turn(value: object, previous_digest: Mapping[str, Any]) -> int:
    try:
        turn = int(value)
    except (TypeError, ValueError):
        try:
            turn = int(previous_digest.get("last_updated_turn") or 0) + 1
        except (TypeError, ValueError):
            turn = 1
    return max(turn, 1)


def normalize_session_digest(
    value: Mapping[str, Any] | None,
    *,
    previous_digest: Mapping[str, Any] | None = None,
    risk_level: str = "L0",
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None

    previous = previous_digest if isinstance(previous_digest, Mapping) else {}
    digest: dict[str, Any] = {"schema_version": DIGEST_SCHEMA_VERSION}

    for field in LIST_FIELDS:
        digest[field] = _safe_list(value.get(field), fallback=previous.get(field), risk_level=risk_level)

    digest["emotional_arc"] = _safe_text(
        value.get("emotional_arc", previous.get("emotional_arc", "")),
        limit=MAX_TEXT_CHARS,
        risk_level=risk_level,
    )
    digest["last_updated_turn"] = _coerce_turn(value.get("last_updated_turn"), previous)
    digest["summary_200chars"] = _safe_text(
        value.get("summary_200chars", previous.get("summary_200chars", "")),
        limit=MAX_SUMMARY_CHARS,
        risk_level=risk_level,
    )

    has_content = any(digest[field] for field in LIST_FIELDS + STRING_FIELDS)
    return digest if has_content else None


def _recent_message_digest(state: Mapping[str, Any], *, limit: int = 6) -> list[dict[str, str]]:
    recent_messages = state.get("recent_messages")
    if not isinstance(recent_messages, list):
        return []
    messages: list[dict[str, str]] = []
    for message in recent_messages[-limit:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = _safe_text(message.get("content"), limit=140, risk_level=str(state.get("risk_level") or "L0"))
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _build_digest_messages(state: Mapping[str, Any]) -> list[dict[str, str]]:
    risk_level = str(state.get("risk_level") or "L0")
    messages = state.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    current_text = _safe_text(
        state.get("normalized_text") or last_user_message(messages) or "",
        limit=260,
        risk_level=risk_level,
    )
    assistant_text = _safe_text(state.get("assistant_text"), limit=260, risk_level=risk_level)
    old_digest = normalize_session_digest(
        state.get("session_digest") if isinstance(state.get("session_digest"), Mapping) else {},
        previous_digest={},
        risk_level=risk_level,
    ) or {}
    payload = {
        "old_session_digest": old_digest,
        "turn": {
            "user_text": current_text,
            "assistant_text": assistant_text,
            "intent": str(state.get("intent") or "other"),
            "risk_level": risk_level,
        },
        "recent_messages": _recent_message_digest(state),
    }

    system_prompt = (
        "你是心理咨询对话系统的内部会话全景更新器。"
        "只返回紧凑 JSON，不要解释，不要 markdown。"
        "你要合并旧 session_digest 与本轮信息，保留稳定主题、情绪走向、有效/无效支持方式、未展开线索和关键变化。"
        "不要逐字保存原话，不要保存邮箱、手机号、身份证、住址等个人标识。"
        "若 risk_level 是 L2 或 L3，只保留概括性安全连续性信息，不记录具体工具、地点、方法等可操作风险细节。"
        "固定字段：key_themes, emotional_arc, effective_interventions, ineffective_interventions, "
        "unresolved_threads, significant_changes, last_updated_turn, summary_200chars。"
        "列表最多 5 项，summary_200chars 不超过 200 个中文字符。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def update_session_digest_with_llm(state: Mapping[str, Any]) -> dict[str, Any] | None:
    risk_level = str(state.get("risk_level") or "L0")
    previous_digest = state.get("session_digest") if isinstance(state.get("session_digest"), Mapping) else {}
    try:
        reply = await asyncio.wait_for(
            deepseek_client.chat(
                _build_digest_messages(state),
                temperature=0,
                max_tokens=700,
                thinking_enabled=False,
            ),
            timeout=DIGEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # pragma: no cover - external service/runtime guard
        logger.warning("Session digest LLM update failed: %s", exc)
        return None

    parsed = _parse_json_object(reply)
    return normalize_session_digest(parsed, previous_digest=previous_digest, risk_level=risk_level)


def fallback_session_summary(state: Mapping[str, Any]) -> str:
    text = str(state.get("normalized_text") or "")
    risk_level = str(state.get("risk_level") or "L0")
    intent = str(state.get("intent") or "other")
    messages = state.get("messages", [])
    topic = excerpt(text or last_user_message(messages if isinstance(messages, list) else []) or "当前困扰", 30)

    if risk_level in {"L2", "L3"}:
        return f"本轮出现明显安全风险：{topic}；后续优先确认是否联系到可信任的人以及当前环境是否安全。"

    focus_map = {
        "vent": "近期压力和情绪困扰",
        "soothe": "焦虑或身体紧绷",
        "light_counseling": "想理清事情与下一步",
        "daily_checkin": "当天的情绪状态",
        "other": "最近在意的困扰",
    }
    return f"本轮主题：{focus_map.get(intent, '最近在意的困扰')}；用户提到：{topic}；可延续点：最卡住的那一刻。"
