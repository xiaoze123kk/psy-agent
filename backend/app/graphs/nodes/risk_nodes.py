from __future__ import annotations

from app.graphs.nodes.common import AgentState, contains_any, matched_keywords


RISK_KEYWORDS = {
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
    if contains_any(lowered, RISK_KEYWORDS["suicide_terms"]) and contains_any(lowered, RISK_KEYWORDS["plan_terms"]):
        return "L3"
    if contains_any(lowered, RISK_KEYWORDS["l2_keywords"]) or contains_any(lowered, RISK_KEYWORDS["suicide_terms"]):
        return "L2"
    if contains_any(lowered, RISK_KEYWORDS["l1_keywords"]):
        return "L1"
    return "L0"


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    lowered = text.lower()
    risk_level = sync_risk_classify(text)
    if risk_level == "L3":
        matched = matched_keywords(lowered, RISK_KEYWORDS["suicide_terms"]) + matched_keywords(
            lowered, RISK_KEYWORDS["plan_terms"]
        )
        return {"risk_level": "L3", "risk_reasons": matched[:4] or ["explicit_high_risk_signal"], "intent": "crisis"}
    if risk_level == "L2":
        matched = matched_keywords(lowered, RISK_KEYWORDS["l2_keywords"]) + matched_keywords(
            lowered, RISK_KEYWORDS["suicide_terms"]
        )
        return {"risk_level": "L2", "risk_reasons": matched[:4] or ["high_risk_hint"], "intent": "crisis"}
    if risk_level == "L1":
        matched = matched_keywords(lowered, RISK_KEYWORDS["l1_keywords"])
        return {"risk_level": "L1", "risk_reasons": matched[:3] or ["elevated_distress"]}
    return {"risk_level": "L0", "risk_reasons": []}


async def intent_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "").lower()
    if contains_any(text, ("焦虑", "心慌", "睡不着", "失眠", "慌", "呼吸", "panic", "anxious", "sleep")):
        return {"intent": "soothe"}
    if contains_any(text, ("分析", "复盘", "理一理", "怎么办", "想办法", "help me sort", "analyze")):
        return {"intent": "light_counseling"}
    if contains_any(text, ("难受", "委屈", "想哭", "没人理解", "压力好大", "压抑", "崩溃", "sad", "cry", "overwhelmed")):
        return {"intent": "vent"}
    if contains_any(text, ("今天", "刚刚", "这会儿", "today i feel")):
        return {"intent": "daily_checkin"}
    return {"intent": "other"}
