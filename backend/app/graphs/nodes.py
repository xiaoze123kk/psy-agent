from app.graphs.state import AgentState


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


async def normalize_input(state: AgentState) -> AgentState:
    normalized_text = (state.get("user_text") or state.get("voice_transcript") or "").strip()
    return {
        "normalized_text": normalized_text,
        "messages": state.get("messages", []),
        "input_type": state.get("input_type", "text"),
    }


async def load_user_profile(state: AgentState) -> AgentState:
    user_mode = state.get("user_mode", "adult")
    return {
        "profile": {
            "user_mode": user_mode,
            "nickname": "user",
        },
        "companion_preferences": {
            "style": "gentle",
            "question_tolerance": "low" if user_mode == "teen" else "medium",
        },
        "memory_mode": state.get("memory_mode", "summary_only"),
        "response_style": {
            "short_sentences": user_mode == "teen",
            "tone": "supportive",
        },
    }


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()

    l3_keywords = {
        "suicide plan",
        "kill myself tonight",
        "end my life tonight",
        "自杀计划",
        "结束生命",
        "今晚就",
    }
    l2_keywords = {
        "want to disappear",
        "want to die",
        "cannot control myself",
        "活着没意思",
        "想消失",
        "不想活了",
        "控制不住自己",
    }
    l1_keywords = {
        "panic",
        "anxious",
        "cannot sleep",
        "焦虑",
        "心慌",
        "睡不着",
        "崩溃",
    }

    if _contains_any(text, l3_keywords):
        return {"risk_level": "L3", "risk_reasons": ["explicit_high_risk_signal"]}
    if _contains_any(text, l2_keywords):
        return {"risk_level": "L2", "risk_reasons": ["high_risk_hint"]}
    if _contains_any(text, l1_keywords):
        return {"risk_level": "L1", "risk_reasons": ["elevated_distress"]}
    return {"risk_level": "L0", "risk_reasons": []}


async def intent_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()
    intent = "other"

    if _contains_any(text, {"what is", "difference", "知识", "是什么", "原理"}):
        intent = "knowledge_qa"
    elif _contains_any(text, {"anime", "character", "动漫", "角色"}):
        intent = "anime_match"
    elif _contains_any(text, {"test result", "mbti", "人格", "测试结果"}):
        intent = "test_interpretation"
    elif _contains_any(text, {"anxious", "panic", "sleep", "焦虑", "心慌", "睡不着"}):
        intent = "soothe"
    elif _contains_any(text, {"analyze", "help me sort", "建议", "梳理", "复盘", "分析"}):
        intent = "light_counseling"
    elif _contains_any(text, {"sad", "cry", "委屈", "难受", "想哭", "没人理解"}):
        intent = "vent"

    return {"intent": intent}


async def knowledge_retrieve(_: AgentState) -> AgentState:
    return {
        "retrieved_knowledge": [
            {
                "title": "knowledge_stub",
                "summary": "A short retrieved knowledge summary.",
            }
        ]
    }


async def test_context(_: AgentState) -> AgentState:
    return {"retrieved_test_context": {"result_code": "INFJ_like"}}


async def anime_context(_: AgentState) -> AgentState:
    return {
        "retrieved_character_context": [
            {"name": "character_stub", "similarity": 0.8}
        ]
    }


async def companion_response(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    return {
        "assistant_text": (
            "I hear you. Thank you for sharing this. "
            "We can go slowly and focus on what feels hardest right now. "
            f"You said: {text[:120]}"
        ),
        "suggested_actions": ["continue", "summarize", "gentle advice"],
    }


async def soothing_response(state: AgentState) -> AgentState:
    return {
        "assistant_text": (
            "Let us pause for one minute. Put both feet on the ground, "
            "inhale slowly, and name five things you can see. "
            "We only need to handle the next three minutes."
        ),
        "suggested_actions": ["60-second grounding", "continue talking", "open SOS"],
    }


async def counseling_response(state: AgentState) -> AgentState:
    return {
        "assistant_text": (
            "Let us break this into one concrete event, your feeling, "
            "your thought, and one next action. "
            "We can start with the event that happened most recently."
        ),
        "suggested_actions": ["event", "feeling", "thought", "next step"],
    }


async def knowledge_response(state: AgentState) -> AgentState:
    knowledge = state.get("retrieved_knowledge", [])
    summary = knowledge[0]["summary"] if knowledge else "No knowledge found."
    return {
        "assistant_text": (
            "Here is a quick explanation first, then we can map it to your situation. "
            f"{summary}"
        ),
        "suggested_actions": ["30-second version", "3-minute version", "apply to me"],
    }


async def test_response(state: AgentState) -> AgentState:
    result_code = state.get("retrieved_test_context", {}).get("result_code", "unknown")
    return {
        "assistant_text": (
            "This result is a mirror, not a label. "
            f"Current code: {result_code}. "
            "We can review strengths, stress blind spots, and one growth action."
        ),
        "suggested_actions": ["strengths", "blind spots", "growth action"],
    }


async def anime_response(state: AgentState) -> AgentState:
    top_character = "character_stub"
    if state.get("retrieved_character_context"):
        top_character = state["retrieved_character_context"][0]["name"]
    return {
        "assistant_text": (
            "Top match is ready. You are similar in coping style and relationship rhythm. "
            f"Top character: {top_character}. "
            "We can talk about where you are similar and where you are different."
        ),
        "suggested_actions": ["why similar", "where different", "growth line"],
    }


async def crisis_response(state: AgentState) -> AgentState:
    return {
        "assistant_text": (
            "Your safety matters most right now. "
            "I want you to contact a trusted person immediately and use local emergency resources. "
            "We can keep this focused on immediate safety steps."
        ),
        "suggested_actions": ["contact trusted person", "open SOS", "local emergency"],
    }


async def summarize_turn(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    return {
        "session_summary": f"topic={text[:60]} risk={state.get('risk_level', 'L0')}",
    }


async def memory_candidate_extract(state: AgentState) -> AgentState:
    if state.get("memory_mode") == "off":
        return {"memory_candidates": []}
    summary = state.get("session_summary", "")
    candidate = {
        "memory_type": "state",
        "content": summary,
        "importance": 3,
    }
    return {"memory_candidates": [candidate]}


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
