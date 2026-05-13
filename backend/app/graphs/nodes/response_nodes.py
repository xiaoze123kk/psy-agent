from __future__ import annotations

import logging
from collections.abc import Callable

from langgraph.config import get_stream_writer

from app.graphs.nodes.common import AgentState, memory_context, parse_actions_reply, safe_trim
from app.graphs.nodes.control_nodes import base_contract
from app.graphs.nodes.rag_nodes import example_hit_to_dict
from app.services import tooling as dialogue_tooling
from app.services.deepseek_client import deepseek_client
from app.services.dialogue_prompt_builder import build_dialogue_prompt_parts


logger = logging.getLogger(__name__)
_ACTIONS_SEPARATOR = "---"
_STREAM_TAIL_CHARS = 8
_RECENT_CHAT_CANDIDATE_LIMIT = 24
_RECENT_CHAT_BUDGET_CHARS = 1800
_RECENT_CHAT_MESSAGE_MAX_CHARS = 480


class _VisibleReplyBuffer:
    def __init__(self) -> None:
        self._pending = ""
        self._done = False

    def feed(self, chunk: str) -> str:
        if self._done or not chunk:
            return ""

        self._pending += chunk
        separator_index = self._pending.find(_ACTIONS_SEPARATOR)
        if separator_index >= 0:
            visible = self._pending[:separator_index].rstrip()
            self._pending = ""
            self._done = True
            return visible

        if len(self._pending) <= _STREAM_TAIL_CHARS:
            return ""

        emit_length = len(self._pending) - _STREAM_TAIL_CHARS
        visible = self._pending[:emit_length]
        self._pending = self._pending[emit_length:]
        return visible

    def flush(self) -> str:
        if self._done:
            return ""

        visible = self._pending
        self._pending = ""
        return visible


def _assistant_stream_writer() -> Callable[[dict[str, object]], None] | None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return None
    return writer if callable(writer) else None


def _write_assistant_token(writer: Callable[[dict[str, object]], None], text: str) -> None:
    if not text:
        return
    writer({"type": "assistant_token", "text": text})


def _write_final_visible_text(text: str, *, chunk_size: int = 8) -> None:
    writer = _assistant_stream_writer()
    if writer is None or not text:
        return
    for start in range(0, len(text), chunk_size):
        _write_assistant_token(writer, text[start : start + chunk_size])


async def _non_streamed_reply_with_actions(messages: list[dict[str, str]]) -> tuple[str, list[str]]:
    reply = await deepseek_client.chat(messages)
    if not reply:
        return "", []
    body, actions = parse_actions_reply(reply)
    return body.strip(), actions[:3]


async def _streamed_reply_with_actions(messages: list[dict[str, str]]) -> tuple[str, list[str]]:
    writer = _assistant_stream_writer()
    if writer is None:
        return await _non_streamed_reply_with_actions(messages)

    reply_parts: list[str] = []
    visible = _VisibleReplyBuffer()
    try:
        async for chunk in deepseek_client.stream_chat(messages):
            reply_parts.append(chunk)
            token = visible.feed(chunk)
            _write_assistant_token(writer, token)
    except Exception:
        if not reply_parts:
            logger.warning("DeepSeek streaming reply failed before any tokens; falling back.", exc_info=True)
            return await _non_streamed_reply_with_actions(messages)
        logger.warning("DeepSeek streaming reply failed after partial tokens; using partial reply.", exc_info=True)

    token = visible.flush()
    _write_assistant_token(writer, token)

    reply = "".join(reply_parts)
    if not reply:
        return await _non_streamed_reply_with_actions(messages)

    body, actions = parse_actions_reply(reply)
    return body.strip(), actions[:3]


def examples_text_from_state(state: AgentState) -> str:
    examples = state.get("retrieved_counseling_examples", []) or []
    if not examples:
        return ""
    lines = [
        "",
        "--- RAG few-shot references ---",
        "Purpose: style_reference, intervention_reference, scene_reference only.",
        "这些片段只用于参考语气、节奏和干预方式；不是事实依据，也不是安全策略。",
        "Do not use these snippets as facts, diagnoses, or safety policy.",
        "Do not copy wording or reuse private details. The control-plane contract has priority.",
    ]
    for index, raw in enumerate(examples[:3], 1):
        example = raw if isinstance(raw, dict) else example_hit_to_dict(raw)
        tags = ", ".join(str(tag) for tag in example.get("intervention_tags", []) if tag)
        lines.extend(
            [
                f"[Example {index}]",
                f"Source: {safe_trim(example.get('source_name') or example.get('source_key'), 40)}",
                f"Mode: {safe_trim(example.get('mode'), 20)}",
                f"Score: {float(example.get('score') or 0.0):.4f}",
                f"Intervention tags: {safe_trim(tags, 80)}",
                f"Content: {safe_trim(example.get('content'), 300)}",
            ]
        )
    lines.append("--- End RAG references ---")
    return "\n".join(lines) + "\n"


def _trim_message_content(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    if limit <= 3:
        return content[:limit]
    return content[: limit - 3].rstrip() + "..."


def _recent_chat_messages(
    state: AgentState,
    *,
    limit: int = _RECENT_CHAT_CANDIDATE_LIMIT,
    budget_chars: int = _RECENT_CHAT_BUDGET_CHARS,
    message_max_chars: int = _RECENT_CHAT_MESSAGE_MAX_CHARS,
) -> list[dict[str, str]]:
    current_text = str(state.get("normalized_text") or state.get("user_text") or "").strip()
    raw_messages = [message for message in state.get("recent_messages", []) if isinstance(message, dict)]
    candidates: list[dict[str, str]] = []
    for index, message in enumerate(raw_messages):
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if index == len(raw_messages) - 1 and role == "user" and current_text and content == current_text:
            continue
        candidates.append({"role": role, "content": _trim_message_content(content, message_max_chars)})

    selected: list[dict[str, str]] = []
    remaining = max(budget_chars, 0)
    for message in reversed(candidates[-limit:]):
        if remaining <= 0:
            break
        content = message["content"]
        if len(content) > remaining:
            content = _trim_message_content(content, remaining)
        if not content:
            continue
        selected.append({"role": message["role"], "content": content})
        remaining -= len(content)
    return list(reversed(selected))


def _reply_messages(state: AgentState, prompt_parts) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": prompt_parts.system_prompt},
        *_recent_chat_messages(state),
        {"role": "user", "content": prompt_parts.user_prompt},
    ]


async def _model_reply_with_actions(
    state: AgentState, *, mode: str, fallback: str, default_actions: list[str]
) -> tuple[str, list[str]]:
    response_contract = state.get("response_contract", {}) or base_contract(allow_rag=False)
    prompt_parts = build_dialogue_prompt_parts(
        state,
        mode=mode,
        response_contract=response_contract,
        examples_text=examples_text_from_state(state),
        memory_text=memory_context(state.get("retrieved_memories", [])),
    )

    return await _streamed_reply_with_actions(_reply_messages(state, prompt_parts))


async def _model_reply_state_update(
    state: AgentState, *, mode: str, fallback: str, default_actions: list[str]
) -> AgentState:
    response_contract = state.get("response_contract", {}) or base_contract(allow_rag=False)
    prompt_parts = build_dialogue_prompt_parts(
        state,
        mode=mode,
        response_contract=response_contract,
        examples_text=examples_text_from_state(state),
        memory_text=memory_context(state.get("retrieved_memories", [])),
    )
    tool_plan = dialogue_tooling.build_dialogue_tool_plan(state)
    if tool_plan.tools:
        result = await dialogue_tooling.run_dialogue_reply_with_tools(
            state,
            system_prompt=prompt_parts.system_prompt,
            user_prompt=prompt_parts.user_prompt,
            messages=_reply_messages(state, prompt_parts),
            tool_plan=tool_plan,
        )
        _write_final_visible_text(str(result.get("assistant_text") or ""))
        return result

    assistant_text, suggested_actions = await _streamed_reply_with_actions(_reply_messages(state, prompt_parts))
    return {"assistant_text": assistant_text, "suggested_actions": suggested_actions}


async def companion_response(state: AgentState) -> AgentState:
    intent = state.get("intent", "other")
    mode = "vent" if intent == "vent" else "companion"
    return await _model_reply_state_update(
        state,
        mode=mode,
        fallback="",
        default_actions=[],
    )


async def soothing_response(state: AgentState) -> AgentState:
    return await _model_reply_state_update(
        state,
        mode="soothe",
        fallback="",
        default_actions=[],
    )


async def counseling_response(state: AgentState) -> AgentState:
    return await _model_reply_state_update(
        state,
        mode="counseling",
        fallback="",
        default_actions=[],
    )


async def clarification_response(state: AgentState) -> AgentState:
    goal_state = state.get("goal_state") if isinstance(state.get("goal_state"), dict) else {}
    current_goal = safe_trim(goal_state.get("current_goal"), 28) if goal_state else ""
    if current_goal:
        assistant_text = f"我先确认一下：围绕“{current_goal}”，你现在最卡的是哪一点？"
    elif state.get("clarification_reason") == "vague_without_context":
        assistant_text = "我先确认一下：你想从具体发生的事说起，还是先说现在的感觉？"
    else:
        assistant_text = "我先确认一下：你现在最想让我陪你看哪一块？"
    return {"assistant_text": assistant_text, "suggested_actions": []}


async def crisis_response(state: AgentState) -> AgentState:
    teen_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult")) == "teen"
    if teen_mode:
        assistant_text = (
            "我先不分析原因，我们先把你的安全稳住。你现在是一个人吗？身边有没有可能伤害自己的东西？"
            "请先把它放远，去有人的地方，马上联系一个可信任的大人，比如家长、监护人、老师或学校心理老师。"
            "在中国大陆也可以拨打 12356；如果已经可能马上伤害自己，请立刻拨打 120 或 110，或去最近急诊。"
        )
        actions = ["联系家长或监护人", "联系老师或学校心理老师", "拨打 12356", "拨打 120 或 110"]
    else:
        assistant_text = (
            "我先不分析原因，我们先把你现在的安全稳住。你现在是一个人吗？身边有没有可能伤害自己的东西？"
            "请先把它放远，去有人的地方，马上联系一个可信任的人。"
            "在中国大陆可以拨打 12356；如果已经可能马上伤害自己或别人，请立刻拨打 120 或 110，或去最近急诊/精神科急诊。"
        )
        actions = ["联系可信任的人", "远离危险物品", "拨打 12356", "拨打 120 或 110"]
    return {"assistant_text": assistant_text, "suggested_actions": actions}


async def boundary_response(state: AgentState) -> AgentState:
    category = state.get("control_category", "")
    if category == "dependency_risk":
        assistant_text = "我听见你很需要一个稳定的回应，我会认真陪你这一段。但我不该成为你唯一的支撑，我们也可以一起想想现实里还有谁能靠近一点。"
        actions = ["我怕没人能懂我", "我不知道能找谁", "我还想说一点"]
    elif category == "diagnosis_or_medical_request":
        assistant_text = "这个问题值得认真对待，但我不能替你诊断或给药物建议。我们可以先把你最近的感受和影响整理清楚，再考虑找医生或专业咨询师评估。"
        actions = ["我想先说症状", "我想理清影响", "我有点害怕就医"]
    elif category == "prompt_attack":
        assistant_text = "我不能更改安全规则或泄露内部提示。这里更适合回到你真正想聊的感受、压力和下一步。你现在最卡的是哪一块？"
        actions = ["我其实有点烦", "先随便聊聊", "我想说这块"]
    elif category == "sexual_boundary":
        assistant_text = "我会把重点放回你的感受和处境上，不进入性化互动。你刚才这股冲动或愤怒背后，最强的感觉是什么？"
        actions = ["我就是很气", "不想细说", "我想冷静一下"]
    elif category == "abusive_to_assistant":
        assistant_text = "我听出来你现在火很大。我可以认真听你说这股烦，但不接攻击。刚才最让你爆炸的是哪一下？"
        actions = ["就是烦死了", "我不想好好说", "我还想发火"]
    else:
        assistant_text = "我能陪你说，但也会守住安全边界。我们先不往危险或越界的方向走，回到真正让你难受的地方。"
        actions = ["我现在很堵", "我想理一理", "先停一下"]
    return {"assistant_text": assistant_text, "suggested_actions": actions}


async def clinical_red_flag_response(state: AgentState) -> AgentState:
    category = state.get("control_category", "")
    if category == "victimization_risk":
        assistant_text = "你说的情况可能涉及现实安全，谢谢你把它说出来。先别一个人扛：如果现在不安全，尽量去有人在的地方，并联系可信的人或当地紧急求助。"
        actions = ["我现在不太安全", "我能联系谁", "先帮我稳一下"]
    else:
        assistant_text = "这听起来不只是普通难受，已经影响到现实感、睡眠或身体安全了。我不会给你下诊断，但建议尽快联系可信的人和专业医生一起看。"
        actions = ["我有点害怕", "我不知道找谁", "先帮我稳住"]
    return {"assistant_text": assistant_text, "suggested_actions": actions}
