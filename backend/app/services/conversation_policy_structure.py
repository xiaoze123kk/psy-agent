from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.services.conversation_policy_anchors import LIGHT_CHAT_TERMS, has_any


def recent_assistant_opening_mode(messages: Sequence[Mapping[str, object]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if content.startswith(("听起来", "我听见", "我听到", "我能理解", "我理解")):
            return "formulaic_reflection"
        if content.startswith("《"):
            return "direct"
        if content:
            return "other"
    return "none"


def recent_assistant_contents(messages: Sequence[Mapping[str, object]], *, limit: int = 3) -> list[str]:
    contents: list[str] = []
    for message in messages:
        if str(message.get("role") or "") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            contents.append(content)
    return contents[-limit:]


def reply_structure_signature(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", stripped) if part.strip()]
    question_count = stripped.count("？") + stripped.count("?")
    compact = "".join(stripped.split())
    if question_count > 0 and len(paragraphs) >= 2:
        return "two_beat_question"
    if question_count > 0 and stripped.startswith(("听起来", "我听见", "我听到", "我能理解", "我理解")):
        return "two_beat_question"
    if len(compact) <= 80 and question_count == 0:
        return "brief_answer"
    if question_count == 0 and has_any(stripped, ("先停", "放在这里", "不用急着", "不推进", "停一会儿")):
        return "pause_then_invite"
    if len(paragraphs) <= 1:
        return "single_paragraph"
    return "multi_paragraph"


def recent_reused_structure(messages: Sequence[Mapping[str, object]]) -> str:
    signatures = [
        reply_structure_signature(content)
        for content in recent_assistant_contents(messages)
    ]
    signatures = [
        signature
        for signature in signatures
        if signature in {"two_beat_question", "single_paragraph", "brief_answer", "pause_then_invite"}
    ]
    if len(signatures) >= 2 and signatures[-1] == signatures[-2]:
        return signatures[-1]
    return ""


def base_structure_mode(conversation_move: str, text: str) -> str:
    compact = "".join(text.split())
    if conversation_move == "micro_step":
        return "brief_answer"
    if conversation_move == "ordinary_chat":
        if len(compact) <= 20 or has_any(text, LIGHT_CHAT_TERMS):
            return "brief_answer"
        return "single_paragraph"
    if conversation_move in {"continue_thread", "respond_to_anchor", "post_risk_return", "correction_followup"}:
        return "single_paragraph"
    if conversation_move == "soft_invitation":
        return "pause_then_invite"
    return "single_paragraph"


def structure_mode_for(conversation_move: str, text: str, messages: Sequence[Mapping[str, object]]) -> tuple[str, str]:
    base = base_structure_mode(conversation_move, text)
    avoid_structure = recent_reused_structure(messages)
    if avoid_structure == "two_beat_question":
        return "single_paragraph", avoid_structure
    if avoid_structure == "single_paragraph" and base == "single_paragraph":
        if conversation_move in {"continue_thread", "respond_to_anchor", "post_risk_return"}:
            return "pause_then_invite", avoid_structure
        return "brief_answer", avoid_structure
    if avoid_structure == "brief_answer" and base == "brief_answer":
        return "single_paragraph", avoid_structure
    if avoid_structure == "pause_then_invite" and base == "pause_then_invite":
        return "single_paragraph", avoid_structure
    return base, avoid_structure


def structure_style(mode: str, avoid_structure: str) -> str:
    descriptions = {
        "single_paragraph": "用一段自然话接住，不强行拆成“共情-整理-追问”。",
        "brief_answer": "短一点直接回，不补流程感。",
        "pause_then_invite": "可以停在陈述或轻邀请，不急着追问。",
    }
    style = f"{mode}，{descriptions.get(mode, '让回复节奏和上一轮有所变化。')}"
    if avoid_structure == "two_beat_question":
        return f"{style} 避免复用上一轮的两段式整理+追问。"
    if avoid_structure:
        return f"{style} 避免连续复用上一轮的 {avoid_structure} 结构。"
    return f"{style} 不要把每轮都写成同一种节奏。"
