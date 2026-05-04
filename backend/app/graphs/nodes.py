from app.graphs.state import AgentState
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
    for memory in memories[:4]:
        content = str(memory.get("content", "")).strip()
        if content:
            lines.append(f"- {content}")
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
    return reply or fallback


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


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()
    suicide_terms = (
        "自杀",
        "结束生命",
        "不想活了",
        "活着没意义",
        "去死",
        "kill myself",
        "end my life",
        "want to die",
    )
    plan_terms = (
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
    )
    l2_keywords = (
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
    )
    l1_keywords = (
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
    )

    if _contains_any(text, suicide_terms) and _contains_any(text, plan_terms):
        matched = _matched_keywords(text, suicide_terms) + _matched_keywords(text, plan_terms)
        return {
            "risk_level": "L3",
            "risk_reasons": matched[:4] or ["explicit_high_risk_signal"],
            "intent": "crisis",
        }
    if _contains_any(text, l2_keywords) or _contains_any(text, suicide_terms):
        matched = _matched_keywords(text, l2_keywords) + _matched_keywords(text, suicide_terms)
        return {
            "risk_level": "L2",
            "risk_reasons": matched[:4] or ["high_risk_hint"],
            "intent": "crisis",
        }
    if _contains_any(text, l1_keywords):
        matched = _matched_keywords(text, l1_keywords)
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
    text = state.get("normalized_text", "")
    intent = state.get("intent", "other")
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    companion_style = state.get("companion_preferences", {}).get("style", "gentle")
    last_summary = state.get("last_summary", "")
    excerpt = _excerpt(text or _last_user_message(state.get("messages", [])) or "这件事")

    if last_summary:
        opener = f"我记得你上次聊到“{_excerpt(last_summary, 28)}”，这次我继续接住你。"
    elif companion_style == "steady":
        opener = "我们先把节奏放慢，我会陪你把重点抓出来。"
    elif user_mode == "teen":
        opener = "我在，你不用急着把一切都讲清楚。"
    else:
        opener = "我在，先不用急着把事情讲完整。"

    if intent == "vent":
        body = "听起来你已经憋了很久，也很想被真正理解。"
        actions = ["继续说", "我想被理解", "给我一个小建议"]
    elif intent == "daily_checkin":
        body = "谢谢你把今天的状态带过来，能说出来已经很不容易。"
        actions = ["说说今天发生了什么", "先聊情绪", "先聊压力源"]
    else:
        body = "你可以先只说此刻最卡住、最难受的那一小块。"
        actions = ["继续说", "帮我理一理", "先听我说完"]

    fallback = (
        f"{opener}{body}"
        f" 你刚刚提到“{excerpt}”。如果你愿意，我们先从这里慢慢展开。"
    )
    mode = "vent" if intent == "vent" else "companion"
    return {
        "assistant_text": await _model_reply(state, mode=mode, fallback=fallback),
        "suggested_actions": actions,
    }


async def soothing_response(state: AgentState) -> AgentState:
    user_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult"))
    tail = (
        "等身体稍微稳一点，我们再看刚才是什么触发了你。"
        if user_mode == "adult"
        else "先稳住身体，再聊刚才发生了什么。"
    )
    fallback = (
        "先不急着分析，先把身体拉回到当下。"
        "试着做三步：双脚踩地，慢慢吸气 4 秒呼气 6 秒做 3 轮，"
        "再说出你眼前看到的 3 样东西。"
        f"{tail}"
    )
    return {
        "assistant_text": await _model_reply(state, mode="soothe", fallback=fallback),
        "suggested_actions": ["跟我做 60 秒稳定练习", "继续聊触发点", "打开 SOS"],
    }


async def counseling_response(state: AgentState) -> AgentState:
    fallback = (
        "我们先把这件事拆小一点，不急着得出结论。"
        "先说最近一次发生了什么，再说那一刻你脑子里冒出的第一句话，"
        "最后只找一个最小的下一步。"
    )
    return {
        "assistant_text": await _model_reply(state, mode="counseling", fallback=fallback),
        "suggested_actions": ["先说发生了什么", "帮我理清想法", "一起定下一步"],
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
        actions = ["联系家长或监护人", "联系老师或班主任", "打开 SOS", "拨打 120 或 110"]
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
        summary = f"上次主要在聊{focus}：{topic}；下次可以从最卡住的那一刻继续说。"

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
