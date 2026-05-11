from __future__ import annotations

from app.graphs.state import AgentState


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = str(text or "").lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def excerpt(text: str, limit: int = 24) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def last_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def memory_context(memories: list[dict]) -> str:
    lines = []
    for memory in memories[:5]:
        content = str(memory.get("content", "")).strip()
        if not content:
            continue
        memory_type = str(memory.get("memory_type", "memory")).strip()
        title = str(memory.get("title", "")).strip()
        why_selected = str(memory.get("why_selected", "")).strip()
        freshness_warning = str(memory.get("freshness_warning", "")).strip()
        prefix = f"[{memory_type}] "
        body = f"{title}：{content}" if title and title not in content else content
        detail_parts = [part for part in (why_selected, freshness_warning) if part]
        suffix = f"（{'；'.join(detail_parts)}）" if detail_parts else ""
        lines.append(f"- {prefix}{body}{suffix}")
    return "\n".join(lines) or "无"


def recent_context(state: AgentState, count: int = 6) -> str:
    messages = state.get("recent_messages", [])
    if not messages:
        return "（暂无历史对话）"
    lines = []
    for message in messages[-count:]:
        role = "用户" if message.get("role") == "user" else "陪伴者"
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines) or "（暂无历史对话）"


def parse_actions_reply(text: str | None) -> tuple[str, list[str]]:
    if not text:
        return "", []
    text = text.strip()
    if "---" not in text:
        return text, []
    body, actions_block = text.rsplit("---", 1)
    actions: list[str] = []
    for action in actions_block.strip().splitlines():
        item = action.strip().lstrip("0123456789.、- ").strip()
        if item:
            actions.append(item)
    return body.strip(), actions[:3]


def has_any_text(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def matched_text(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = str(text or "").lower()
    return [term for term in terms if term.lower() in lowered]


def safe_trim(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
