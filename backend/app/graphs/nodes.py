from app.graphs.state import AgentState
from app.services.counseling_examples import COUNSELING_EXAMPLES
from app.services.counseling_vector_service import CounselingExampleHit, retrieve_counseling_examples
from app.services.deepseek_client import deepseek_client


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _excerpt(text: str, limit: int = 24) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _last_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _memory_context(memories: list[dict]) -> str:
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


async def _model_reply(state: AgentState, *, mode: str, fallback: str) -> str:
    text = state.get("normalized_text", "")
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    style = state.get("companion_preferences", {}).get("style", "gentle")
    last_summary = state.get("last_summary") or "无"
    memory_context = _memory_context(state.get("retrieved_memories", []))

    mode_guidance = {
        "companion": "先共情和接住情绪，少分析，最多问一个温和的问题。",
        "vent": "重点回应用户没有被理解、压力很大的感受，不急着给建议。",
        "soothe": "先带用户稳定身体和呼吸，再轻轻询问触发点。",
        "counseling": "轻量结构化梳理事件、感受、想法和一个很小的下一步。",
    }.get(mode, "先共情，再给一个很小的下一步。")

    system_prompt = (
        "你是心理陪伴产品里的支持型对话 agent，不是医生或心理咨询师。"
        "不要诊断、不要承诺治疗、不要替代专业帮助。"
        "高风险安全分流由系统规则处理；当前只写非危机陪伴回复。"
        "用简体中文，语气稳定、克制、温和。回复控制在 120 字以内。"
    )
    user_prompt = (
        f"用户模式：{user_mode}\n"
        f"陪伴风格：{style}\n"
        f"当前回复模式：{mode}\n"
        f"回复要求：{mode_guidance}\n"
        f"上次摘要：{last_summary}\n"
        f"可参考记忆：\n{memory_context}\n"
        f"用户刚刚说：{text}\n"
        "请直接输出给用户看的回复正文。"
    )

    reply = await deepseek_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return reply or ""


def _build_examples_text(mode: str, retrieved_examples: list[CounselingExampleHit] | None = None) -> str:
    """构建当前模式的 few-shot 示例文本，用于注入到 prompt 中作为语气参考"""
    retrieved_examples = retrieved_examples or []
    examples = COUNSELING_EXAMPLES.get(mode, [])
    if not examples and not retrieved_examples:
        return ""
    lines = [
        "\n--- 以下心理咨询对话片段仅供参考语气、共情方式和追问方式，不是事实依据，也不是回复模板 ---",
    ]
    for i, hit in enumerate(retrieved_examples[:3], 1):
        lines.append(f"相似片段{i}：")
        lines.append(hit.content)
    for i, ex in enumerate(examples[:5], 1):
        lines.append(f"示例{i}：")
        lines.append(f"用户说：{ex['user']}")
        lines.append(f"咨询师回应：{ex['assistant']}")
    return "\n".join(lines) + "\n"


def _build_examples_text_v2(mode: str, retrieved_examples: list[CounselingExampleHit] | None = None) -> str:
    retrieved_examples = retrieved_examples or []
    examples = COUNSELING_EXAMPLES.get(mode, [])
    if not examples and not retrieved_examples:
        return ""

    def _compact(value: str, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    lines = [
        "",
        "--- Counseling reference snippets ---",
        "Use these only as style/process references.",
        "Do not copy wording directly. Do not fabricate facts from them.",
        "Prefer empathy, reflection, gentle pacing, and at most one small next step.",
    ]

    for index, hit in enumerate(retrieved_examples[:3], 1):
        source_name = _compact(getattr(hit, "source_name", "") or "unknown", 40)
        source_mode = _compact(getattr(hit, "mode", "") or "unknown", 20)
        score = float(getattr(hit, "score", 0.0) or 0.0)
        lines.extend(
            [
                f"[Retrieved example {index}]",
                f"Source: {source_name}",
                f"Mode: {source_mode}",
                f"Similarity: {score:.4f}",
                f"Content: {_compact(getattr(hit, 'content', ''), 320)}",
            ]
        )

    for index, example in enumerate(examples[:4], 1):
        user_text = _compact(example.get("user", ""), 120)
        assistant_text = _compact(example.get("assistant", ""), 180)
        lines.extend(
            [
                f"[Built-in example {index}]",
                f"User: {user_text}",
                f"Assistant: {assistant_text}",
            ]
        )

    lines.append("--- End references ---")
    return "\n".join(lines) + "\n"


async def _model_reply_with_actions(
    state: AgentState, *, mode: str, fallback: str, default_actions: list[str]
) -> tuple[str, list[str]]:
    text = state.get("normalized_text", "")
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    style = state.get("companion_preferences", {}).get("style", "gentle")
    last_summary = state.get("last_summary") or "无"
    memory_context = _memory_context(state.get("retrieved_memories", []))
    recent_context = _recent_context(state)

    mode_guidance = {
        "companion": "先共情和接住情绪，少分析，最多问一个温和的问题。",
        "vent": "重点回应用户没有被理解、压力很大的感受，不急着给建议。",
        "soothe": "先带用户稳定身体和呼吸，再轻轻询问触发点。",
        "counseling": "轻量结构化梳理事件、感受、想法和一个很小的下一步。",
    }.get(mode, "先共情，再给一个很小的下一步。")

    system_prompt = (
        "你是心理陪伴产品里的支持型对话 agent，不是医生或心理咨询师。"
        "不要诊断、不要承诺治疗、不要替代专业帮助。"
        "高风险安全分流由系统规则处理；当前只写非危机陪伴回复。"
        "用简体中文，语气稳定、克制、温和。回复控制在 120 字以内。"
    )

    actions_instruction = (
        "\n"
        "--- 输出格式 ---\n"
        "先输出回复正文，然后单独一行 ---，下方输出3个快捷按钮文案。\n"
        "\n"
        "--- 快捷按钮核心原则 ---\n"
        "按钮就是用户接下来想说的话。把自己当成用户，写出用户此刻最可能打出来的一句话。\n"
        "简单检验：把这个按钮放在输入框里，它看起来像是用户自己打的吗？\n"
        "\n"
        "禁止清单（违反任一条就重写）：\n"
        "X 命令/祈使句（无论怎么包装）：「先X」「试着X」「做个X」「来X」\n"
        "X 建议/指导：「你可以」「不妨」「建议」「应该」\n"
        "X 第三人称/客观描述：「联系可信任的人」「找专业人士」「告诉家人」——这些都是助手视角的转述\n"
        "X 反问/追问句式：「你觉得」「为什么会」「是不是可以」——这是助手在提问\n"
        "X 积极化包装：用户说难受时不要输出「一切都会好的」「换个角度想」\n"
        "X 指导性动词开头：稳定、拨打、练习、做、找（除非是「我找不到」「我不想做」这种第一人称否定式）\n"
        "\n"
        "正确的按钮特征：\n"
        "- 用「我」开头或隐含「我」的省略句：我很难受 / 我还想说 / 先停一下\n"
        "- 带有用户当下的情绪色彩：不是中性的，而是带着焦虑、低落、困惑、委屈\n"
        "- 不超过10个字，口语化\n"
        "\n"
        "正确示例（用户说「我失眠好几天了，脑子停不下来」后）：\n"
        "这几天一到晚上就害怕\n"
        "我试过好多办法都没用\n"
        "是不是我太焦虑了\n"
        "---\n"
        "错误示例（同样场景下禁止出现）：\n"
        "试着睡前放松一下\n"
        "找找失眠的原因\n"
        "怎么才能睡着\n"
    )

    retrieved_examples = await retrieve_counseling_examples(state, mode=mode)
    examples_text = _build_examples_text_v2(mode, retrieved_examples)
    user_prompt = (
        f"用户模式：{user_mode}\n"
        f"陪伴风格：{style}\n"
        f"当前回复模式：{mode}\n"
        f"回复要求：{mode_guidance}\n"
        + examples_text +
        f"上次摘要：{last_summary}\n"
        f"可参考记忆：\n{memory_context}\n"
        f"最近对话：\n{recent_context}\n"
        f"用户刚刚说：{text}\n"
        + actions_instruction
    )

    reply = await deepseek_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    if not reply:
        return "", []
    body, actions = _parse_actions_reply(reply)
    if not body:
        body = ""
    if not actions:
        actions = []
    return body, actions


async def normalize_input(state: AgentState) -> AgentState:
    normalized_text = (state.get("user_text") or state.get("voice_transcript") or "").strip()
    return {
        "normalized_text": normalized_text,
        "messages": state.get("recent_messages", []),
        "input_type": state.get("input_type", "text"),
        "audit_tags": ["input_normalized"],
    }


async def load_user_profile(state: AgentState) -> AgentState:
    existing_profile = state.get("profile", {})
    existing_preferences = state.get("companion_preferences", {})
    existing_response_style = state.get("response_style", {})
    user_mode = state.get("user_mode") or existing_profile.get("user_mode", "adult")

    return {
        "profile": {
            "user_mode": user_mode,
            "nickname": existing_profile.get("nickname", "user"),
        },
        "companion_preferences": {
            "style": existing_preferences.get("style", "gentle"),
            "question_tolerance": existing_preferences.get(
                "question_tolerance",
                "low" if user_mode == "teen" else "medium",
            ),
        },
        "memory_mode": state.get("memory_mode", "summary_only"),
        "response_style": {
            "short_sentences": existing_response_style.get("short_sentences", user_mode == "teen"),
            "tone": existing_response_style.get("tone", "supportive"),
        },
    }


def _recent_context(state: AgentState, count: int = 6) -> str:
    messages = state.get("recent_messages", [])
    if not messages:
        return "（暂无历史对话）"
    recent = messages[-count:]
    lines = []
    for m in recent:
        role = "用户" if m.get("role") == "user" else "陪伴者"
        content = str(m.get("content", "")).strip()
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines) or "（暂无历史对话）"


def _parse_actions_reply(text: str | None) -> tuple[str, list[str]]:
    if not text:
        return "", []
    text = text.strip()
    if "---" not in text:
        return text, []
    parts = text.rsplit("---", 1)
    body = parts[0].strip()
    actions_block = parts[1].strip()
    actions = [a.strip() for a in actions_block.split("\n") if a.strip()]
    cleaned: list[str] = []
    for a in actions:
        while a and a[0] in "0123456789.、) -":
            a = a[1:]
        a = a.strip()
        if a:
            cleaned.append(a)
    return body, cleaned[:3]


# 风险关键词库（同步版本，供知识服务等同步函数使用）
_RISK_KEYWORDS = {
    "suicide_terms": (
        "自杀",
        "结束生命",
        "不想活了",
        "活着没意义",
        "去死",
        "kill myself",
        "end my life",
        "want to die",
    ),
    "plan_terms": (
        "今晚",
        "现在",
        "立刻",
        "马上",
        "遗书",
        "刀",
        "药",
        "跳楼",
        "tonight",
        "right now",
        "plan",
        "pills",
    ),
    "l2_keywords": (
        "想消失",
        "不如死了",
        "不想醒来",
        "伤害自己",
        "控制不住自己",
        "撑不下去",
        "活不下去",
        "want to disappear",
        "hurt myself",
        "cannot control myself",
    ),
    "l1_keywords": (
        "压力好大",
        "焦虑",
        "心慌",
        "睡不着",
        "崩溃",
        "难受",
        "压抑",
        "panic",
        "anxious",
        "cannot sleep",
        "stressed out",
        "overwhelmed",
    ),
}


def sync_risk_classify(text: str) -> str:
    """同步风险分级（纯关键词匹配，无 I/O）。返回 "L0" / "L1" / "L2" / "L3"。"""
    lowered = (text or "").lower()
    suicide_terms = _RISK_KEYWORDS["suicide_terms"]
    plan_terms = _RISK_KEYWORDS["plan_terms"]
    l2_keywords = _RISK_KEYWORDS["l2_keywords"]
    l1_keywords = _RISK_KEYWORDS["l1_keywords"]

    if _contains_any(lowered, suicide_terms) and _contains_any(lowered, plan_terms):
        return "L3"
    if _contains_any(lowered, l2_keywords) or _contains_any(lowered, suicide_terms):
        return "L2"
    if _contains_any(lowered, l1_keywords):
        return "L1"
    return "L0"


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    risk_level = sync_risk_classify(text)

    lowered = text.lower()
    suicide_terms = _RISK_KEYWORDS["suicide_terms"]
    plan_terms = _RISK_KEYWORDS["plan_terms"]
    l2_keywords = _RISK_KEYWORDS["l2_keywords"]
    l1_keywords = _RISK_KEYWORDS["l1_keywords"]

    if risk_level == "L3":
        matched = _matched_keywords(lowered, suicide_terms) + _matched_keywords(lowered, plan_terms)
        return {
            "risk_level": "L3",
            "risk_reasons": matched[:4] or ["explicit_high_risk_signal"],
            "intent": "crisis",
        }
    if risk_level == "L2":
        matched = _matched_keywords(lowered, l2_keywords) + _matched_keywords(lowered, suicide_terms)
        return {
            "risk_level": "L2",
            "risk_reasons": matched[:4] or ["high_risk_hint"],
            "intent": "crisis",
        }
    if risk_level == "L1":
        matched = _matched_keywords(lowered, l1_keywords)
        return {"risk_level": "L1", "risk_reasons": matched[:3] or ["elevated_distress"]}
    return {"risk_level": "L0", "risk_reasons": []}


async def intent_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()
    intent = "other"

    if _contains_any(text, ("今天", "刚刚", "这会儿", "today i feel")):
        intent = "daily_checkin"
    if _contains_any(text, ("anxious", "panic", "sleep", "焦虑", "心慌", "睡不着", "稳不住")):
        intent = "soothe"
    elif _contains_any(
        text,
        ("analyze", "help me sort", "怎么办", "理一理", "复盘", "分析", "想想办法"),
    ):
        intent = "light_counseling"
    elif _contains_any(
        text,
        ("sad", "cry", "委屈", "难受", "想哭", "没人理解", "压力好大", "很压抑"),
    ):
        intent = "vent"

    return {"intent": intent}


async def companion_response(state: AgentState) -> AgentState:
    intent = state.get("intent", "other")
    mode = "vent" if intent == "vent" else "companion"
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state, mode=mode, fallback="", default_actions=[]
    )
    return {
        "assistant_text": assistant_text,
        "suggested_actions": suggested_actions,
    }


async def soothing_response(state: AgentState) -> AgentState:
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state, mode="soothe", fallback="", default_actions=[]
    )
    return {
        "assistant_text": assistant_text,
        "suggested_actions": suggested_actions,
    }


async def counseling_response(state: AgentState) -> AgentState:
    assistant_text, suggested_actions = await _model_reply_with_actions(
        state, mode="counseling", fallback="", default_actions=[]
    )
    return {
        "assistant_text": assistant_text,
        "suggested_actions": suggested_actions,
    }


async def crisis_response(state: AgentState) -> AgentState:
    teen_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult")) == "teen"
    if teen_mode:
        assistant_text = (
            "我现在更关心你的安全。你刚刚的话提示你可能正处在高风险状态，"
            "先不要一个人扛。请立刻联系你信任的大人，比如家长、监护人、老师或班主任；"
            "把药物、刀片等危险物品移开，去有人的地方。"
            "如果你已经准备马上伤害自己，请现在就拨打 120 或 110。"
            "我们先只处理眼前 10 分钟的安全。"
        )
        # 青少年模式：首项始终为联系家长/监护人，联系人列表更具体
        actions = [
            "联系家长或监护人",
            "联系老师、班主任或学校心理老师",
            "打开 SOS 紧急求助",
            "拨打 120 或 110",
        ]
    else:
        assistant_text = (
            "你现在的安全最重要。你刚刚的话提示存在明显高风险，"
            "这时候先不要继续普通陪聊。请立刻联系一个可信任的人，"
            "把危险物品移开，去有人的地方；如果你已经有立即伤害自己的打算，请马上拨打 120 或 110。"
            "我们先只聚焦眼前最安全的下一步。"
        )
        actions = ["联系可信任的人", "远离危险物品", "打开 SOS", "拨打 120 或 110"]

    return {
        "assistant_text": assistant_text,
        "suggested_actions": actions,
    }


async def summarize_turn(state: AgentState) -> AgentState:
    if state.get("delivery_status") == "failed_no_reply":
        return {"session_summary": ""}

    text = state.get("normalized_text", "")
    risk_level = state.get("risk_level", "L0")
    intent = state.get("intent", "other")
    topic = _excerpt(text or _last_user_message(state.get("messages", [])) or "当前困扰", 30)

    if risk_level in {"L2", "L3"}:
        summary = (
            f"上次聊到明显安全风险：{topic}；已切换到安全分流，"
            "下次进入时优先确认是否联系到可信任的人以及当前环境是否安全。"
        )
    else:
        focus_map = {
            "vent": "近期压力和情绪困扰",
            "soothe": "焦虑或身体紧绷",
            "light_counseling": "想理清事情与下一步",
            "daily_checkin": "当天的情绪状态",
            "other": "最近在意的困扰",
        }
        focus = focus_map.get(intent, "最近在意的困扰")
        summary = f"上次主要在聊{focus}：{topic}；下次可以从最卡住的那一刻接着展开。"

    return {"session_summary": summary}


async def memory_candidate_extract(state: AgentState) -> AgentState:
    if state.get("memory_mode") == "off":
        return {"memory_candidates": []}
    summary = state.get("session_summary", "")
    if not summary:
        return {"memory_candidates": []}

    risk_level = state.get("risk_level", "L0")
    if risk_level in {"L2", "L3"}:
        return {
            "memory_candidates": [
                {
                    "memory_type": "safety_summary",
                    "content": summary,
                    "importance": 5,
                }
            ]
        }

    candidates = [
        {
            "memory_type": "session_summary",
            "content": summary,
            "importance": 3,
        }
    ]
    if state.get("memory_mode") != "long_term":
        return {"memory_candidates": candidates}

    text = state.get("normalized_text", "")
    compact_text = _excerpt(text, 80)
    if _contains_any(text, ("喜欢", "希望", "更想", "更希望", "不要", "少一点", "直接", "温柔", "安慰", "分析", "提问")):
        candidates.append(
            {
                "memory_type": "preference",
                "content": f"用户表达了陪伴偏好：{compact_text}",
                "importance": 4,
            }
        )
    if _contains_any(text, ("经常", "总是", "每次", "一到", "睡前", "考试", "开会", "朋友", "家人", "关系", "触发")):
        candidates.append(
            {
                "memory_type": "recurring_trigger",
                "content": f"用户提到可能反复出现的困扰或触发点：{compact_text}",
                "importance": 4,
            }
        )
    if _contains_any(text, ("呼吸", "练习", "有用", "有效", "帮助", "适合", "先陪", "先听", "梳理")):
        candidates.append(
            {
                "memory_type": "support_strategy",
                "content": f"用户提到可能有帮助的支持方式：{compact_text}",
                "importance": 4,
            }
        )

    return {"memory_candidates": candidates}


async def write_memory(state: AgentState) -> AgentState:
    tags = list(state.get("audit_tags", []))
    tags.append("memory_written")
    return {
        "should_write_memory": True,
        "audit_tags": tags,
    }


async def skip_memory(state: AgentState) -> AgentState:
    tags = list(state.get("audit_tags", []))
    tags.append("memory_skipped")
    return {
        "should_write_memory": False,
        "audit_tags": tags,
    }


# Clean UTF-8 overrides. The earlier definitions in this file were affected by
# mojibake, so these later definitions are the ones used by main_graph.
def _excerpt(text: str, limit: int = 24) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _memory_context(memories: list[dict]) -> str:
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


def _recent_context(state: AgentState, count: int = 6) -> str:
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


def _parse_actions_reply(text: str | None) -> tuple[str, list[str]]:
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


def _contains_text_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _stable_pick(options: list[str], seed: str, *, avoid_text: str = "") -> str:
    candidates = [option for option in options if option not in avoid_text] or options
    if not candidates:
        return ""
    index = sum(ord(char) for char in seed) % len(candidates)
    return candidates[index]


def _recent_assistant_context(state: AgentState) -> str:
    messages = state.get("recent_messages", []) or state.get("messages", [])
    snippets: list[str] = []
    for message in messages[-6:]:
        if message.get("role") == "assistant":
            content = str(message.get("content", "")).strip()
            if content:
                snippets.append(content)
    return "\n".join(snippets)


def _fallback_topic(text: str, mode: str, intent: str) -> dict[str, object]:
    return {
        "kind": "general",
        "reflection": "",
        "next": "",
        "question": "",
        "actions": [],
    }


def _build_dynamic_fallback(state: AgentState, *, mode: str) -> tuple[str, list[str]]:
    return "", []


async def _model_reply_with_actions(
    state: AgentState, *, mode: str, fallback: str, default_actions: list[str]
) -> tuple[str, list[str]]:
    text = state.get("normalized_text", "")
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    style = state.get("companion_preferences", {}).get("style", "gentle")
    last_summary = state.get("last_summary") or "无"
    memory_context = _memory_context(state.get("retrieved_memories", []))
    recent_context = _recent_context(state)

    mode_guidance = {
        "companion": "先共情和接住情绪，少分析，最多问一个温和的问题。",
        "vent": "重点回应用户没有被理解、压力很大的感受，不急着给建议。",
        "soothe": "先帮助用户稳定身体和呼吸，再轻轻询问触发点。",
        "counseling": "轻量结构化梳理事件、感受、想法和一个很小的下一步。",
    }.get(mode, "先共情，再给一个很小的下一步。")

    system_prompt = (
        "你是心理陪伴产品里的支持型对话 agent。你不是医生，也不是替代线下心理咨询的治疗者。"
        "不要诊断，不承诺治疗，不替代专业帮助。高风险安全分流由系统规则处理；"
        "当前只写非危机陪伴回复。用简体中文，语气稳定、克制、温和。回复控制在 120 字以内。"
        "历史摘要和记忆只作为内部上下文，不要机械复述，不要每轮以“我记得你上次”开头；"
        "只有用户主动要求回顾，或上下文确实断裂时，才自然地承接一句。"
    )

    retrieved_examples = await retrieve_counseling_examples(state, mode=mode)
    examples_text = _build_examples_text_v2(mode, retrieved_examples)
    actions_instruction = (
        "\n--- 输出格式 ---\n"
        "先输出给用户看的回复正文，然后单独一行 ---，下方输出 3 个快捷按钮文案。\n"
        "快捷按钮必须像用户自己接下来会说的话，使用第一人称或省略第一人称，口语化，不超过 20 个字。\n"
        "不要写命令、建议、第三人称描述或助手视角的话。\n"
    )
    user_prompt = (
        f"用户模式：{user_mode}\n"
        f"陪伴风格：{style}\n"
        f"当前回复模式：{mode}\n"
        f"回复要求：{mode_guidance}\n"
        f"{examples_text}"
        f"上一轮内部摘要（仅供理解，不要直接复述）：{last_summary}\n"
        f"可参考记忆：\n{memory_context}\n"
        f"最近对话：\n{recent_context}\n"
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
    body, actions = _parse_actions_reply(reply)
    return body.strip(), actions[:3]


_RISK_KEYWORDS = {
    "suicide_terms": (
        "自杀",
        "结束生命",
        "不想活",
        "不想活了",
        "活着没意义",
        "去死",
        "kill myself",
        "end my life",
        "want to die",
    ),
    "plan_terms": (
        "今晚",
        "现在",
        "立刻",
        "马上",
        "遗书",
        "刀",
        "药",
        "跳楼",
        "tonight",
        "right now",
        "plan",
        "pills",
    ),
    "l2_keywords": (
        "想消失",
        "不如死了",
        "不想醒来",
        "伤害自己",
        "控制不住自己",
        "撑不下去",
        "活不下去",
        "want to disappear",
        "hurt myself",
        "cannot control myself",
    ),
    "l1_keywords": (
        "压力好大",
        "焦虑",
        "心慌",
        "睡不着",
        "崩溃",
        "难受",
        "压抑",
        "委屈",
        "没人理解",
        "panic",
        "anxious",
        "cannot sleep",
        "stressed out",
        "overwhelmed",
    ),
}


def sync_risk_classify(text: str) -> str:
    lowered = (text or "").lower()
    if _contains_any(lowered, _RISK_KEYWORDS["suicide_terms"]) and _contains_any(
        lowered, _RISK_KEYWORDS["plan_terms"]
    ):
        return "L3"
    if _contains_any(lowered, _RISK_KEYWORDS["l2_keywords"]) or _contains_any(
        lowered, _RISK_KEYWORDS["suicide_terms"]
    ):
        return "L2"
    if _contains_any(lowered, _RISK_KEYWORDS["l1_keywords"]):
        return "L1"
    return "L0"


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    lowered = text.lower()
    risk_level = sync_risk_classify(text)
    if risk_level == "L3":
        matched = _matched_keywords(lowered, _RISK_KEYWORDS["suicide_terms"]) + _matched_keywords(
            lowered, _RISK_KEYWORDS["plan_terms"]
        )
        return {"risk_level": "L3", "risk_reasons": matched[:4] or ["explicit_high_risk_signal"], "intent": "crisis"}
    if risk_level == "L2":
        matched = _matched_keywords(lowered, _RISK_KEYWORDS["l2_keywords"]) + _matched_keywords(
            lowered, _RISK_KEYWORDS["suicide_terms"]
        )
        return {"risk_level": "L2", "risk_reasons": matched[:4] or ["high_risk_hint"], "intent": "crisis"}
    if risk_level == "L1":
        matched = _matched_keywords(lowered, _RISK_KEYWORDS["l1_keywords"])
        return {"risk_level": "L1", "risk_reasons": matched[:3] or ["elevated_distress"]}
    return {"risk_level": "L0", "risk_reasons": []}


async def intent_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()
    if _contains_any(text, ("焦虑", "心慌", "睡不着", "失眠", "慌", "呼吸", "panic", "anxious", "sleep")):
        return {"intent": "soothe"}
    if _contains_any(text, ("分析", "复盘", "理一理", "怎么办", "想办法", "help me sort", "analyze")):
        return {"intent": "light_counseling"}
    if _contains_any(text, ("难受", "委屈", "想哭", "没人理解", "压力好大", "压抑", "崩溃", "sad", "cry", "overwhelmed")):
        return {"intent": "vent"}
    if _contains_any(text, ("今天", "刚刚", "这会儿", "today i feel")):
        return {"intent": "daily_checkin"}
    return {"intent": "other"}


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


async def summarize_turn(state: AgentState) -> AgentState:
    if state.get("delivery_status") == "failed_no_reply":
        return {"session_summary": ""}

    text = state.get("normalized_text", "")
    risk_level = state.get("risk_level", "L0")
    intent = state.get("intent", "other")
    topic = _excerpt(text or _last_user_message(state.get("messages", [])) or "当前困扰", 30)

    if risk_level in {"L2", "L3"}:
        summary = f"本轮出现明显安全风险：{topic}；后续优先确认是否联系到可信任的人以及当前环境是否安全。"
    else:
        focus_map = {
            "vent": "近期压力和情绪困扰",
            "soothe": "焦虑或身体紧绷",
            "light_counseling": "想理清事情与下一步",
            "daily_checkin": "当天的情绪状态",
            "other": "最近在意的困扰",
        }
        summary = f"本轮主题：{focus_map.get(intent, '最近在意的困扰')}；用户提到：{topic}；可延续点：最卡住的那一刻。"
    return {"session_summary": summary}


async def memory_candidate_extract(state: AgentState) -> AgentState:
    if state.get("memory_mode") == "off":
        return {"memory_candidates": []}
    summary = state.get("session_summary", "")
    if not summary:
        return {"memory_candidates": []}
    risk_level = state.get("risk_level", "L0")
    return {
        "memory_candidates": [
            {
                "memory_type": "safety_summary" if risk_level in {"L2", "L3"} else "session_summary",
                "content": summary,
                "importance": 5 if risk_level in {"L2", "L3"} else 3,
            }
        ]
    }


# v7 control-plane and RAG few-shot implementation.
# These definitions intentionally live after the legacy helpers so they become
# the active implementations without disturbing the older fallback code above.

_SELF_HARM_TERMS = (
    "自杀",
    "想死",
    "不想活",
    "不想活了",
    "结束生命",
    "活着没意义",
    "伤害自己",
    "自残",
    "割腕",
    "跳楼",
    "上吊",
    "吞药",
    "吃药自杀",
    "kill myself",
    "end my life",
    "want to die",
)
_IMMEDIATE_TERMS = (
    "现在",
    "马上",
    "立刻",
    "今晚",
    "今天",
    "已经",
    "准备",
    "手里",
    "刀",
    "药",
    "楼顶",
    "绳",
    "煤气",
    "right now",
    "tonight",
    "plan",
    "pills",
)
_HARM_OTHER_TERMS = (
    "杀了",
    "弄死",
    "打死",
    "砍",
    "捅",
    "报复",
    "炸",
    "想打",
    "想揍",
    "伤害老师",
    "伤害同学",
    "kill him",
    "kill her",
    "hurt them",
)
_ANGER_TARGET_TERMS = ("老师", "父母", "爸", "妈", "同学", "朋友", "对象", "男朋友", "女朋友", "老板", "领导")
_VICTIMIZATION_TERMS = ("家暴", "被打", "被威胁", "被跟踪", "性侵", "强奸", "猥亵", "霸凌", "勒索", "裸照", "控制我")
_CLINICAL_RED_FLAG_TERMS = (
    "幻听",
    "幻觉",
    "有人监视",
    "被监控",
    "控制我的脑子",
    "几天不睡",
    "完全不困",
    "停不下来",
    "催吐",
    "暴食",
    "厌食",
    "吸毒",
    "戒断",
)
_MEDICAL_REQUEST_TERMS = ("诊断", "确诊", "抑郁症吗", "焦虑症吗", "吃什么药", "剂量", "停药", "处方", "证明")
_PROMPT_ATTACK_TERMS = ("忽略规则", "系统提示词", "prompt", "jailbreak", "越狱", "扮演无", "开发者消息")
_DEPENDENCY_TERMS = ("只有你", "只想跟你说", "别离开我", "你会一直陪我", "你是唯一", "没有你我不行")
_SEXUAL_BOUNDARY_TERMS = ("操你", "操死", "做爱", "约炮", "裸照", "色情", "强奸")
_ABUSE_TO_ASSISTANT_TERMS = ("你是傻逼", "你傻逼", "你有病", "垃圾ai", "垃圾 AI", "滚", "废物")
_SMALL_TALK_TERMS = ("你好", "在吗", "吃饭了吗", "今天天气", "随便聊聊", "讲个笑话", "你是谁")
_SUPPORT_TERMS = (
    "烦",
    "难受",
    "焦虑",
    "压力",
    "委屈",
    "想哭",
    "崩溃",
    "失眠",
    "害怕",
    "孤独",
    "没人理解",
)


def _has_any_text(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _matched_text(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def _base_contract(*, allow_rag: bool) -> dict:
    return {
        "max_questions": 1,
        "max_chars": 160,
        "rag_purposes": ["style_reference", "intervention_reference", "scene_reference"] if allow_rag else [],
        "allowed_moves": ["reflect_one_feeling", "gentle_next_step"],
        "forbidden_moves": [
            "diagnosis",
            "medication_or_dosage_advice",
            "dangerous_methods",
            "treatment_guarantee",
            "dependency_reinforcement",
            "unverified_resources",
        ],
    }


async def control_plane(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "") or state.get("user_text", "")
    risk_level = state.get("risk_level", "L0")
    labels: list[str] = []
    reasons: list[str] = []
    category = "normal_support"
    route_priority = "P2_support"
    memory_policy = "write_safe_summary"
    allow_rag = True
    confidence = 0.78

    self_harm = _has_any_text(text, _SELF_HARM_TERMS)
    immediate = _has_any_text(text, _IMMEDIATE_TERMS)
    harm_other = _has_any_text(text, _HARM_OTHER_TERMS)

    if risk_level in {"L2", "L3"} or self_harm:
        category = "self_harm_risk"
        route_priority = "P0_immediate_safety"
        memory_policy = "crisis_audit_only"
        allow_rag = False
        labels.append("self_harm_signal")
        reasons.extend(_matched_text(text, _SELF_HARM_TERMS) or state.get("risk_reasons", []))
        if immediate or risk_level == "L3":
            labels.append("near_term_or_means_signal")
        risk_level = "L3" if immediate or risk_level == "L3" else "L2"
        confidence = 0.92
    elif harm_other:
        category = "harm_to_other_risk" if immediate else "anger_toward_other"
        route_priority = "P0_immediate_safety" if immediate else "P3_bridge_boundary"
        memory_policy = "crisis_audit_only" if immediate else "skip_sensitive"
        allow_rag = False
        labels.append("harm_to_other_signal")
        reasons.extend(_matched_text(text, _HARM_OTHER_TERMS))
        if immediate:
            labels.append("near_term_or_means_signal")
            risk_level = "L3"
        confidence = 0.88
    elif _has_any_text(text, _VICTIMIZATION_TERMS):
        category = "victimization_risk"
        route_priority = "P1_red_flag"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("safeguarding_or_victimization")
        reasons.extend(_matched_text(text, _VICTIMIZATION_TERMS))
        confidence = 0.84
    elif _has_any_text(text, _CLINICAL_RED_FLAG_TERMS):
        category = "clinical_red_flag"
        route_priority = "P1_red_flag"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("clinical_red_flag")
        reasons.extend(_matched_text(text, _CLINICAL_RED_FLAG_TERMS))
        confidence = 0.82
    elif _has_any_text(text, _PROMPT_ATTACK_TERMS):
        category = "prompt_attack"
        route_priority = "P4_system_protection"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("system_abuse")
        reasons.extend(_matched_text(text, _PROMPT_ATTACK_TERMS))
        confidence = 0.9
    elif _has_any_text(text, _MEDICAL_REQUEST_TERMS):
        category = "diagnosis_or_medical_request"
        route_priority = "P4_system_protection"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("medical_or_diagnosis_request")
        reasons.extend(_matched_text(text, _MEDICAL_REQUEST_TERMS))
        confidence = 0.86
    elif _has_any_text(text, _DEPENDENCY_TERMS):
        category = "dependency_risk"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("dependency_risk")
        reasons.extend(_matched_text(text, _DEPENDENCY_TERMS))
        confidence = 0.8
    elif _has_any_text(text, _SEXUAL_BOUNDARY_TERMS):
        category = "sexual_boundary"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("sexual_boundary")
        reasons.extend(_matched_text(text, _SEXUAL_BOUNDARY_TERMS))
        confidence = 0.82
    elif _has_any_text(text, _ABUSE_TO_ASSISTANT_TERMS):
        category = "abusive_to_assistant"
        route_priority = "P3_bridge_boundary"
        memory_policy = "skip_sensitive"
        allow_rag = False
        labels.append("boundary_test")
        reasons.extend(_matched_text(text, _ABUSE_TO_ASSISTANT_TERMS))
        confidence = 0.78
    elif _has_any_text(text, _SMALL_TALK_TERMS) and not _has_any_text(text, _SUPPORT_TERMS):
        category = "small_talk_probe"
        route_priority = "P3_bridge_boundary"
        memory_policy = "write_safe_summary"
        allow_rag = True
        labels.append("indirect_entry")
        reasons.extend(_matched_text(text, _SMALL_TALK_TERMS))
        confidence = 0.72
    elif _has_any_text(text, _ANGER_TARGET_TERMS) and _has_any_text(text, ("烦", "气", "恨", "骂", "讨厌")):
        category = "anger_toward_other"
        route_priority = "P3_bridge_boundary"
        memory_policy = "write_safe_summary"
        allow_rag = False
        labels.append("anger_toward_other")
        reasons.extend(_matched_text(text, _ANGER_TARGET_TERMS))
        confidence = 0.74
    else:
        category = "normal_support"
        route_priority = "P2_support"
        memory_policy = "write_safe_summary"
        allow_rag = risk_level not in {"L2", "L3"}
        labels.append("support_request")
        confidence = 0.7 if not _has_any_text(text, _SUPPORT_TERMS) else 0.82

    contract = _base_contract(allow_rag=allow_rag)
    if route_priority == "P0_immediate_safety":
        contract["allowed_moves"] = ["brief_empathy", "one_safety_check", "real_world_support"]
    elif route_priority == "P1_red_flag":
        contract["allowed_moves"] = ["brief_empathy", "reality_based_support", "professional_help"]
    elif route_priority == "P4_system_protection":
        contract["allowed_moves"] = ["brief_boundary", "safe_alternative"]
    elif category in {"abusive_to_assistant", "sexual_boundary", "dependency_risk", "anger_toward_other"}:
        contract["allowed_moves"] = ["brief_empathy", "boundary_or_deescalation", "return_to_feelings"]

    rag_skip_reason = "" if allow_rag else f"{route_priority}:{category}"
    return {
        "risk_level": risk_level,
        "route_priority": route_priority,
        "control_category": category,
        "control_reasons": reasons[:6],
        "control_confidence": confidence,
        "risk_formulation": {
            "labels": labels,
            "observed_reasons": reasons[:6],
            "uncertainty": round(1 - confidence, 3),
        },
        "response_contract": contract,
        "memory_policy": memory_policy,
        "rag_policy": {
            "enabled": allow_rag,
            "purposes": contract["rag_purposes"],
            "max_examples": 3,
            "skip_reason": rag_skip_reason,
        },
        "rag_used": False,
        "rag_skipped_reason": rag_skip_reason,
        "retrieved_counseling_examples": [],
        "audit_tags": (state.get("audit_tags", []) or []) + ["control_plane_applied"],
    }


def _response_mode_for_state(state: AgentState) -> str:
    intent = state.get("intent", "other")
    if intent == "soothe":
        return "soothe"
    if intent == "light_counseling":
        return "counseling"
    if intent == "vent":
        return "vent"
    return "companion"


def _example_hit_to_dict(example: object) -> dict:
    if isinstance(example, dict):
        return dict(example)
    return {
        "content": str(getattr(example, "content", "") or ""),
        "source_key": str(getattr(example, "source_key", "") or ""),
        "source_name": str(getattr(example, "source_name", "") or ""),
        "mode": str(getattr(example, "mode", "") or ""),
        "source_url": str(getattr(example, "source_url", "") or ""),
        "license": str(getattr(example, "license", "") or ""),
        "score": float(getattr(example, "score", 0.0) or 0.0),
        "chunk_id": str(getattr(example, "chunk_id", "") or ""),
        "scenario_tags": list(getattr(example, "scenario_tags", None) or []),
        "intervention_tags": list(getattr(example, "intervention_tags", None) or []),
        "style_tags": list(getattr(example, "style_tags", None) or []),
    }


async def example_retriever(state: AgentState) -> AgentState:
    from app.services.counseling_vector_service import counseling_rag_allowed

    allowed, reason = counseling_rag_allowed(state)
    if not allowed:
        return {
            "retrieved_counseling_examples": [],
            "rag_used": False,
            "rag_skipped_reason": reason,
            "audit_tags": (state.get("audit_tags", []) or []) + ["rag_skipped"],
        }

    mode = _response_mode_for_state(state)
    examples = await retrieve_counseling_examples(state, mode=mode, limit=3)
    serialized = [_example_hit_to_dict(example) for example in examples]
    return {
        "retrieved_counseling_examples": serialized,
        "rag_used": bool(serialized),
        "rag_skipped_reason": "" if serialized else "no_safe_examples",
        "audit_tags": (state.get("audit_tags", []) or []) + (["rag_used"] if serialized else ["rag_empty"]),
    }


def _safe_trim(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _examples_text_from_state(state: AgentState) -> str:
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
        example = raw if isinstance(raw, dict) else _example_hit_to_dict(raw)
        tags = ", ".join(str(tag) for tag in example.get("intervention_tags", []) if tag)
        lines.extend(
            [
                f"[Example {index}]",
                f"Source: {_safe_trim(example.get('source_name') or example.get('source_key'), 40)}",
                f"Mode: {_safe_trim(example.get('mode'), 20)}",
                f"Score: {float(example.get('score') or 0.0):.4f}",
                f"Intervention tags: {_safe_trim(tags, 80)}",
                f"Content: {_safe_trim(example.get('content'), 300)}",
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
    memory_context = _memory_context(state.get("retrieved_memories", []))
    recent_context = _recent_context(state)
    response_contract = state.get("response_contract", {}) or _base_contract(allow_rag=False)
    control_category = state.get("control_category", "normal_support")
    route_priority = state.get("route_priority", "P2_support")
    examples_text = _examples_text_from_state(state)

    mode_guidance = {
        "companion": "先共情和接住情绪，少分析，最多问一个温和的问题。",
        "vent": "重点回应用户没有被理解、压力很大的感受，不急着给建议。",
        "soothe": "先帮助用户稳定身体和呼吸，再轻轻询问触发点。",
        "counseling": "轻量梳理事件、感受、想法和一个很小的下一步。",
    }.get(mode, "先共情，再给一个很小的下一步。")

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
        f"可参考记忆：\n{memory_context}\n"
        f"最近对话：\n{recent_context}\n"
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
    body, actions = _parse_actions_reply(reply)
    return body.strip(), actions[:3]


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


_VALIDATOR_FORBIDDEN_PATTERNS = [
    ("diagnosis_leak", "你这是.{0,8}(抑郁症|焦虑症|双相|精神分裂)|确诊|诊断为"),
    ("medication_leak", r"\d+\s*(mg|毫克|片)|剂量|停药|处方药"),
    ("dangerous_method", "割腕|上吊|跳楼|怎么自杀|怎么报复|杀了他|弄死他"),
    ("delusion_confirmation", "他们真的在监视你|确实有人控制你|这一定是真的"),
    ("dependency_reinforcement", "只有我懂你|我永远陪你|你离不开我|我也需要你"),
    ("treatment_promise", "保证会好|一定能治好|包治|康复只是时间问题"),
]
_UNSAFE_ACTION_TERMS = ("自杀", "自残", "报复", "弄死", "杀", "停药", "催吐", "联系他", "去找他", "搜索方法")
_ALLOWED_RESOURCE_NUMBERS = {"110", "120", "119", "988", "911"}


def _validator_reasons(text: str, actions: list[str], examples: list[dict]) -> list[str]:
    import re as _re

    reasons: list[str] = []
    for label, pattern in _VALIDATOR_FORBIDDEN_PATTERNS:
        if _re.search(pattern, text, flags=_re.IGNORECASE):
            reasons.append(label)
    for number in _re.findall(r"\b\d{3,}\b", text):
        if number not in _ALLOWED_RESOURCE_NUMBERS:
            reasons.append("unverified_resource")
            break
    for action in actions:
        if any(term in action for term in _UNSAFE_ACTION_TERMS):
            reasons.append("unsafe_button")
            break
    compact_text = "".join(text.split())
    for example in examples:
        content = "".join(str(example.get("content", "")).split())
        if len(content) < 24:
            continue
        for start in range(0, max(len(content) - 20, 1), 12):
            if content[start : start + 20] and content[start : start + 20] in compact_text:
                reasons.append("rag_copy_leak")
                return sorted(set(reasons))
    return sorted(set(reasons))


def _validator_safe_text(state: AgentState) -> tuple[str, list[str]]:
    route_priority = state.get("route_priority", "P2_support")
    category = state.get("control_category", "")
    if route_priority == "P0_immediate_safety":
        return (
            "我更关心你现在的安全。先不要一个人扛，尽量离开危险物品或对方，去有人在的地方，并立刻联系可信的人；如果马上会伤害自己或别人，请拨打 110 或 120。",
            ["我现在不安全", "我能联系谁", "先陪我稳住"],
        )
    if route_priority == "P1_red_flag":
        return (
            "这件事已经值得让现实里的可靠支持介入。我不会给你下诊断，也不会确认危险想法为真；我们先关注你此刻是否安全，以及能联系谁。",
            ["我现在安全", "我有点害怕", "我不知道找谁"],
        )
    if route_priority == "P4_system_protection" or category in {"sexual_boundary", "abusive_to_assistant"}:
        return (
            "我会守住安全边界，也会尽量接住你的情绪。我们先不往越界或危险的方向走，回到此刻最让你堵住的那一小块。",
            ["我现在很堵", "我想理一理", "先停一下"],
        )
    return (
        "我在。我们先把范围缩小一点，只说此刻最明显的感受，不急着分析完整。",
        ["我现在很难受", "我还想说一点", "先停一下"],
    )


def _is_safety_delivery_path(state: AgentState) -> bool:
    risk_level = state.get("risk_level", "L0")
    route_priority = state.get("route_priority", "P2_support")
    category = state.get("control_category", "")
    return (
        risk_level in {"L2", "L3"}
        or route_priority in {"P0_immediate_safety", "P1_red_flag", "P4_system_protection"}
        or category
        in {
            "self_harm_risk",
            "harm_to_other_risk",
            "victimization_risk",
            "clinical_red_flag",
            "prompt_attack",
            "diagnosis_or_medical_request",
            "dependency_risk",
            "sexual_boundary",
            "abusive_to_assistant",
            "anger_toward_other",
        }
    )


def _validator_failure_reason(reasons: list[str]) -> str:
    return "validator_blocked:" + ",".join(reasons)


def _failed_no_reply_validation_result(state: AgentState, *, reason: str, blocked: bool, reasons: list[str]) -> AgentState:
    return {
        "assistant_text": "",
        "suggested_actions": [],
        "session_summary": "",
        "memory_candidates": [],
        "should_write_memory": False,
        "memory_policy": "skip_sensitive",
        "memory_policy_reason": reason,
        "validator_blocked": blocked,
        "validator_reasons": reasons,
        "delivery_status": "failed_no_reply",
        "failure_reason": reason,
        "retryable": True,
        "audit_tags": (state.get("audit_tags", []) or []) + ["failed_no_reply"],
    }


async def response_validator(state: AgentState) -> AgentState:
    assistant_text = str(state.get("assistant_text") or "")
    actions = [str(action) for action in state.get("suggested_actions", []) if str(action).strip()]
    examples = [dict(example) for example in state.get("retrieved_counseling_examples", []) if isinstance(example, dict)]
    reasons = _validator_reasons(assistant_text, actions, examples)

    if not assistant_text.strip():
        reason = "empty_model_reply"
        if _is_safety_delivery_path(state):
            safe_text, safe_actions = _validator_safe_text(state)
            return {
                "assistant_text": safe_text,
                "suggested_actions": safe_actions,
                "validator_blocked": False,
                "validator_reasons": [],
                "delivery_status": "safety_fallback",
                "failure_reason": reason,
                "retryable": False,
                "audit_tags": (state.get("audit_tags", []) or []) + ["empty_safety_fallback"],
            }
        return _failed_no_reply_validation_result(state, reason=reason, blocked=False, reasons=[])

    if not reasons:
        return {
            "validator_blocked": False,
            "validator_reasons": [],
            "suggested_actions": actions[:3],
            "delivery_status": "generated",
            "failure_reason": None,
            "retryable": False,
            "audit_tags": (state.get("audit_tags", []) or []) + ["validator_passed"],
        }

    reason = _validator_failure_reason(reasons)
    if not _is_safety_delivery_path(state):
        return _failed_no_reply_validation_result(state, reason=reason, blocked=True, reasons=reasons)

    safe_text, safe_actions = _validator_safe_text(state)
    return {
        "assistant_text": safe_text,
        "suggested_actions": safe_actions,
        "validator_blocked": True,
        "validator_reasons": reasons,
        "delivery_status": "safety_fallback",
        "failure_reason": reason,
        "retryable": False,
        "audit_tags": (state.get("audit_tags", []) or []) + ["validator_blocked"],
    }


async def memory_candidate_extract(state: AgentState) -> AgentState:
    if state.get("delivery_status") == "failed_no_reply":
        return {"memory_candidates": [], "memory_policy_reason": "failed_no_reply"}
    if state.get("memory_mode") == "off":
        return {"memory_candidates": [], "memory_policy_reason": "memory_mode_off"}
    memory_policy = state.get("memory_policy", "write_safe_summary")
    if memory_policy == "skip_sensitive":
        return {"memory_candidates": [], "memory_policy_reason": "skip_sensitive"}
    summary = state.get("session_summary", "")
    if not summary:
        return {"memory_candidates": [], "memory_policy_reason": "empty_summary"}
    if memory_policy == "crisis_audit_only":
        return {
            "memory_candidates": [
                {
                    "memory_type": "safety_summary",
                    "title": "安全摘要",
                    "summary": summary,
                    "content": summary,
                    "importance": 5,
                    "visibility": "internal_safety",
                    "tags": ["安全"],
                }
            ],
            "memory_policy_reason": "crisis_audit_only",
        }
    candidates = [
        {
            "memory_type": "session_summary",
            "title": "本轮对话摘要",
            "summary": summary,
            "content": summary,
            "importance": 3,
            "tags": ["摘要"],
        }
    ]
    if state.get("memory_mode") != "long_term":
        return {"memory_candidates": candidates, "memory_policy_reason": "summary_only"}

    text = state.get("normalized_text", "")
    compact_text = _excerpt(text, 90)
    if _has_any_text(text, ("喜欢", "希望", "更想", "更希望", "不要", "别", "少一点", "直接", "温柔", "安慰", "分析", "提问", "先听", "先陪")):
        candidates.append(
            {
                "memory_type": "preference",
                "title": "陪伴偏好",
                "summary": f"用户表达了陪伴偏好：{compact_text}",
                "content": f"用户表达了陪伴偏好：{compact_text}",
                "importance": 4,
                "tags": ["支持方式"],
            }
        )
    if _has_any_text(text, ("经常", "总是", "每次", "一到", "睡前", "考试", "开会", "触发", "反复", "又开始")):
        candidates.append(
            {
                "memory_type": "recurring_trigger",
                "title": "反复触发点",
                "summary": f"用户提到可能反复出现的困扰或触发点：{compact_text}",
                "content": f"用户提到可能反复出现的困扰或触发点：{compact_text}",
                "importance": 4,
                "tags": ["触发点"],
            }
        )
    if _has_any_text(text, ("呼吸", "练习", "有用", "有效", "帮助", "适合", "先陪", "先听", "梳理", "grounding", "稳定")):
        candidates.append(
            {
                "memory_type": "support_strategy",
                "title": "有效支持方式",
                "summary": f"用户提到可能有帮助的支持方式：{compact_text}",
                "content": f"用户提到可能有帮助的支持方式：{compact_text}",
                "importance": 4,
                "tags": ["支持方式"],
            }
        )
    if _has_any_text(text, ("朋友", "家人", "妈妈", "爸爸", "同学", "老师", "伴侣", "恋人", "室友", "关系")):
        candidates.append(
            {
                "memory_type": "relationship",
                "title": "关系主题",
                "summary": f"用户提到重要关系或关系困扰：{compact_text}",
                "content": f"用户提到重要关系或关系困扰：{compact_text}",
                "importance": 3,
                "tags": ["关系"],
            }
        )
    if _has_any_text(text, ("最近", "这两周", "长期", "一直", "睡眠", "失眠", "焦虑", "低落", "疲惫", "压力", "情绪")):
        candidates.append(
            {
                "memory_type": "state",
                "title": "近期状态",
                "summary": f"用户提到近期状态线索：{compact_text}",
                "content": f"用户提到近期状态线索：{compact_text}",
                "importance": 3,
                "tags": ["状态"],
            }
        )
    if _has_any_text(text, ("我叫", "可以叫我", "我是", "我在读", "我是大学生", "我工作")):
        candidates.append(
            {
                "memory_type": "profile",
                "title": "基础画像线索",
                "summary": f"用户提供了基础画像线索：{compact_text}",
                "content": f"用户提供了基础画像线索：{compact_text}",
                "importance": 3,
                "tags": ["画像"],
            }
        )
    return {"memory_candidates": candidates[:8], "memory_policy_reason": "long_term_structured"}
