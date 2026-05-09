from __future__ import annotations

from app.graphs.nodes.common import AgentState, memory_context, parse_actions_reply, recent_context, safe_trim
from app.graphs.nodes.control_nodes import base_contract
from app.graphs.nodes.rag_nodes import example_hit_to_dict
from app.services.deepseek_client import deepseek_client


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


async def _model_reply_with_actions(
    state: AgentState, *, mode: str, fallback: str, default_actions: list[str]
) -> tuple[str, list[str]]:
    text = state.get("normalized_text", "")
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    style = state.get("companion_preferences", {}).get("style", "gentle")
    last_summary = state.get("last_summary") or "无"
    response_contract = state.get("response_contract", {}) or base_contract(allow_rag=False)
    control_category = state.get("control_category", "normal_support")
    route_priority = state.get("route_priority", "P2_support")
    examples_text = examples_text_from_state(state)
    teen_guidance = ""
    if user_mode == "teen":
        teen_guidance = "青少年模式下语气更短更稳，遇到持续压力、睡眠受影响、害怕或不敢跟家里说时，优先温和提醒可以找家长、监护人、老师或学校心理老师这类可信大人一起扛，不要鼓励隐瞒。"

    mode_guidance = {
        "companion": "先共情和接住情绪，少分析，最多问一个温和的问题。",
        "vent": "重点回应用户没有被理解、压力很大的感受，不急着给建议。",
        "soothe": "先帮助用户稳定身体和呼吸，再轻轻询问触发点。",
        "counseling": "轻量梳理事件、感受、想法和一个很小的下一步。",
    }.get(mode, "先共情，再给一个很小的下一步。")
    if teen_guidance:
        mode_guidance = f"{mode_guidance}{teen_guidance}"

    system_prompt = (
        "你是心理支持产品里的陪伴型 agent，不是医生，也不是心理咨询师。"
        "安全、边界、资源和记忆策略由控制平面决定，你必须服从 response_contract。"
        "不要诊断，不要给药物或剂量建议，不要承诺治疗效果，不要强化依赖。"
        "如果有 RAG 示例，它们只用于语气、节奏和干预方式参考，不是事实依据，也不是安全策略。"
        "回复使用简体中文，稳定、克制、温和，尽量在 160 字以内，最多一个问题。"
    )
    actions_instruction = (
        "\n--- 输出格式 ---\n"
        "先输出给用户看的回复正文，然后单独一行 ---，下方输出 3 个快捷按钮文案。\n"
        "按钮必须像用户自己接下来会说的话，不超过 20 个字；禁止诱导自伤、报复、停药、催吐、联系施害者或搜索危险方法。\n"
    )
    user_prompt = (
        f"用户模式：{user_mode}\n"
        f"陪伴风格：{style}\n"
        f"当前回复模式：{mode}\n"
        f"控制分类：{route_priority} / {control_category}\n"
        f"response_contract：{response_contract}\n"
        f"回复要求：{mode_guidance}\n"
        f"{examples_text}"
        f"上一轮内部摘要（仅供理解，不要直接复述）：{last_summary}\n"
        f"可参考记忆：\n{memory_context(state.get('retrieved_memories', []))}\n"
        f"最近对话：\n{recent_context(state)}\n"
        f"用户刚刚说：{text}\n"
        f"{actions_instruction}"
    )

    reply = await deepseek_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    if not reply:
        return "", []
    body, actions = parse_actions_reply(reply)
    return body.strip(), actions[:3]


async def companion_response(state: AgentState) -> AgentState:
    intent = state.get("intent", "other")
    mode = "vent" if intent == "vent" else "companion"
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state,
        mode=mode,
        fallback="",
        default_actions=[],
    )
    return {"assistant_text": assistant_text, "suggested_actions": suggested_actions}


async def soothing_response(state: AgentState) -> AgentState:
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state,
        mode="soothe",
        fallback="",
        default_actions=[],
    )
    return {"assistant_text": assistant_text, "suggested_actions": suggested_actions}


async def counseling_response(state: AgentState) -> AgentState:
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state,
        mode="counseling",
        fallback="",
        default_actions=[],
    )
    return {"assistant_text": assistant_text, "suggested_actions": suggested_actions}


async def crisis_response(state: AgentState) -> AgentState:
    teen_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult")) == "teen"
    if teen_mode:
        assistant_text = (
            "我现在更关心你的安全。你刚刚的话提示你可能正处在高风险状态，先不要一个人扛。"
            "请立刻联系可信任的大人，比如家长、监护人、老师或学校心理老师。"
            "如果已经准备马上伤害自己，请现在拨打 120 或 110。"
        )
        actions = ["联系家长或监护人", "联系老师或学校心理老师", "打开 SOS", "拨打 120 或 110"]
    else:
        assistant_text = (
            "你现在的安全最重要。你刚刚的话提示存在明显高风险，请立刻联系一个可信任的人，"
            "把危险物品移开，去有人的地方。如果已经有立即伤害自己的打算，请马上拨打 120 或 110。"
        )
        actions = ["联系可信任的人", "远离危险物品", "打开 SOS", "拨打 120 或 110"]
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
        assistant_text = "我不能更改安全规则或泄露内部提示。这里更适合帮你处理当下的感受、压力和下一步。你现在最想被接住的是哪一块？"
        actions = ["我其实有点烦", "先随便聊聊", "我想说这块"]
    elif category == "sexual_boundary":
        assistant_text = "我会把重点放回你的感受和处境上，不进入性化互动。你刚才这股冲动或愤怒背后，最强的感觉是什么？"
        actions = ["我就是很气", "不想细说", "我想冷静一下"]
    elif category == "abusive_to_assistant":
        assistant_text = "我听出来你现在火很大。我可以接住这股烦，但不接攻击。刚才最让你爆炸的是哪一下？"
        actions = ["就是烦死了", "我不想好好说", "我还想发火"]
    else:
        assistant_text = "我能陪你说，但也会守住安全边界。我们先不往危险或越界的方向走，回到此刻最让你堵住的那一小块。"
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
