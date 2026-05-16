from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}

LITERARY_TERMS = (
    "在轮下",
    "德米安",
    "悉达多",
    "荒原狼",
    "黑塞",
    "卡夫卡",
    "局外人",
    "人间失格",
)
PHILOSOPHICAL_TERMS = (
    "荣格",
    "弗洛伊德",
    "尼采",
    "加缪",
    "萨特",
    "存在主义",
    "原型",
    "阴影",
)
MEDIA_TERMS = ("电影", "电视剧", "动漫", "角色", "剧里", "片子")
DAILY_DETAIL_TERMS = ("花", "包子", "天气", "猫", "饭", "路上", "咖啡", "奶茶")
METAPHOR_TERMS = ("像", "好像", "隐喻", "比喻", "奔跑", "碾死", "轮下", "推着走")
LIGHT_CHAT_TERMS = ("哈哈", "呵呵", "嘿嘿", "笑死", "随便聊", "就聊聊")
DISTRESS_TERMS = (
    "难受",
    "痛苦",
    "崩溃",
    "想哭",
    "焦虑",
    "害怕",
    "失眠",
    "压力",
    "不想活",
    "想死",
)
SHORT_FOLLOWUP_TERMS = ("记得", "嗯", "嗯嗯", "是这个", "对", "就是", "继续", "然后呢")


def _text(state: Mapping[str, Any]) -> str:
    return str(state.get("normalized_text") or state.get("user_text") or "")


def _has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _recent_messages(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = state.get("recent_messages")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [message for message in raw if isinstance(message, Mapping)]


def _recent_high_risk_seen(messages: Sequence[Mapping[str, Any]]) -> bool:
    for message in messages[-6:]:
        if str(message.get("risk_level") or "") in HIGH_RISK_LEVELS:
            return True
    return False


def _extract_book_title(text: str) -> str:
    start = text.find("《")
    end = text.find("》", start + 1)
    if start >= 0 and end > start:
        return text[start + 1 : end].strip()
    return ""


def _anchor_value(text: str, anchor_type: str) -> str:
    book_title = _extract_book_title(text)
    if book_title:
        return book_title
    for terms in (LITERARY_TERMS, PHILOSOPHICAL_TERMS, MEDIA_TERMS, DAILY_DETAIL_TERMS):
        for term in terms:
            if term and term in text:
                return term
    if anchor_type == "metaphor":
        for term in METAPHOR_TERMS:
            if term in text:
                return term
    return ""


def _topic_anchor_type(text: str) -> str:
    if _extract_book_title(text) or _has_any(text, LITERARY_TERMS):
        return "literary"
    if _has_any(text, PHILOSOPHICAL_TERMS):
        return "philosophical"
    if _has_any(text, MEDIA_TERMS):
        return "media"
    if _has_any(text, DAILY_DETAIL_TERMS):
        return "daily_detail"
    if _has_any(text, METAPHOR_TERMS):
        return "metaphor"
    return "none"


def _correction_type(text: str) -> str:
    compact = "".join(text.split())
    if not compact:
        return "none"
    if _has_any(compact, ("别一直问安全", "别问安全", "别盘问安全", "别继续盘问", "不想聊安全")):
        return "too_safety_focused"
    if "安全" in compact and _has_any(compact, ("别问", "不要问", "别一直问", "不要一直问", "别老问", "别追问", "盘问")):
        return "too_safety_focused"
    if _has_any(compact, ("心理分析", "心理化", "别分析", "不要分析", "别心理", "不是要你分析")):
        return "too_psychological"
    if _has_any(compact, ("别一直问", "不要一直问", "别老问", "问题太多", "别追问")):
        return "too_many_questions"
    if _has_any(compact, ("太像ai", "像ai", "像机器", "像客服", "机器人", "机器了")):
        return "too_ai_like"
    if _has_any(compact, ("不是这个意思", "你理解错", "跑偏了", "不是这个")):
        return "not_that_meaning"
    return "none"


def _recent_assistant_opening_mode(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if content.startswith(("听起来", "我听见", "我听到", "我能理解", "我理解")):
            return "formulaic_reflection"
        if content.startswith(("《", "荣格", "黑塞")):
            return "direct"
        if content:
            return "other"
    return "none"


def _is_short_followup(text: str) -> bool:
    compact = "".join(text.split())
    return compact in SHORT_FOLLOWUP_TERMS or (len(compact) <= 4 and _has_any(compact, SHORT_FOLLOWUP_TERMS))


def default_actions_for_conversation_move_policy(policy: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(policy, Mapping):
        return []
    button_style = str(policy.get("button_style") or "")
    move = str(policy.get("conversation_move") or "")
    topic_anchor = str(policy.get("topic_anchor") or "")
    anchor_value = str(policy.get("anchor_value") or "").strip("《》「」“” ")
    if button_style == "topic_continue":
        if anchor_value and topic_anchor == "philosophical":
            return [f"先聊{anchor_value}", f"{anchor_value}这点有意思", "沿着这个聊"]
        if anchor_value and topic_anchor in {"literary", "media", "metaphor"}:
            return [f"先停在{anchor_value}这里", "这个比喻很准", "沿着这个聊"]
        if anchor_value:
            return [f"先说{anchor_value}", f"{anchor_value}这点有意思", "沿着这个聊"]
        return ["这个比喻很准", "沿着这个聊", "先停在这句话上"]
    if button_style == "safety_micro_reply":
        return ["我还在", "先慢一点", "别继续盘问"]
    if button_style == "user_voice":
        if move == "correction_followup":
            if anchor_value:
                return [f"先聊{anchor_value}", "就按这个方向来", "换个说法"]
            return ["先别分析", "就按这个意思来", "换个说法"]
        if anchor_value and topic_anchor == "daily_detail":
            return [f"就聊这{anchor_value}", f"这{anchor_value}挺有意思", "随便聊两句"]
        if anchor_value:
            return [f"就聊{anchor_value}", f"{anchor_value}挺有意思", "随便聊两句"]
        return ["就随便聊聊", "这个挺有意思", "换个轻一点的"]
    return []


def build_conversation_move_policy(state: Mapping[str, Any]) -> dict[str, Any]:
    text = _text(state).strip()
    messages = _recent_messages(state)
    risk_level = str(state.get("risk_level") or "L0")
    risk_policy = state.get("risk_response_policy")
    risk_phase = str(risk_policy.get("risk_phase") if isinstance(risk_policy, Mapping) else state.get("risk_phase") or "")
    correction_type = _correction_type(text)
    anchor_type = _topic_anchor_type(text)
    anchor_value = _anchor_value(text, anchor_type)
    recent_high_risk = _recent_high_risk_seen(messages)

    conversation_move = "soft_invitation"
    button_style = "user_voice"
    psychologizing_risk = "medium"
    anchor_handling = "connect_lightly_to_emotion"
    handling = "轻轻回应用户当下内容，不急着解释成心理模式。"

    if risk_level in HIGH_RISK_LEVELS:
        conversation_move = "micro_step"
        button_style = "safety_micro_reply"
        psychologizing_risk = "low"
        anchor_handling = "treat_as_topic"
        handling = "安全策略优先；只做一个低压小动作，不展开深层分析。"
    elif correction_type != "none":
        conversation_move = "correction_followup"
        button_style = "user_voice"
        psychologizing_risk = "high" if correction_type == "too_psychological" else "medium"
        anchor_handling = "avoid_psychologizing"
        handling = "先体现行为改变，少解释道歉；按用户纠正后的方向继续。"
        if correction_type == "too_safety_focused":
            handling = "先切出安全盘问，承认刚才安全话题还在，但当前先跟着用户聊别的。"
    elif recent_high_risk and risk_level in {"L0", "L1"}:
        conversation_move = "post_risk_return"
        button_style = "topic_continue" if anchor_type not in {"none", "daily_detail"} else "user_voice"
        psychologizing_risk = "medium"
        anchor_handling = "treat_as_topic" if anchor_type != "none" else "connect_lightly_to_emotion"
        handling = "记得刚才的风险，但先回应当前话题；只保留一句低压关照，不主动安全盘问。"
    elif anchor_type in {"literary", "philosophical", "media", "metaphor"}:
        conversation_move = "continue_thread" if _is_short_followup(text) else "respond_to_anchor"
        button_style = "topic_continue"
        psychologizing_risk = "medium"
        anchor_handling = "treat_as_topic"
        handling = "把用户提到的锚点当作真实话题继续聊，轻轻连接处境但不心理化。"
    elif anchor_type == "daily_detail" or _has_any(text, LIGHT_CHAT_TERMS):
        conversation_move = "ordinary_chat"
        button_style = "user_voice"
        psychologizing_risk = "high"
        anchor_handling = "avoid_psychologizing"
        handling = "先当作普通聊天和日常细节处理，不自动解释成压抑、创伤或防御。"
    elif _is_short_followup(text) and messages:
        conversation_move = "continue_thread"
        button_style = "topic_continue"
        psychologizing_risk = "medium"
        anchor_handling = "connect_lightly_to_emotion"
        handling = "顺着前一轮继续，不重新开启咨询流程。"
    elif not _has_any(text, DISTRESS_TERMS):
        conversation_move = "ordinary_chat"
        psychologizing_risk = "high"
        anchor_handling = "avoid_psychologizing"
        handling = "没有明确痛苦、风险或求助时，先按普通聊天处理。"

    opening_mode = "direct"
    if conversation_move in {"ordinary_chat", "correction_followup"}:
        opening_mode = "no_preface"
    elif _recent_assistant_opening_mode(messages) == "formulaic_reflection":
        opening_mode = "direct"
    elif anchor_type not in {"none", "daily_detail"}:
        opening_mode = "echo_anchor"

    return {
        "conversation_move": conversation_move,
        "topic_anchor": anchor_type,
        "anchor_value": anchor_value,
        "anchor_handling": anchor_handling,
        "handling": handling,
        "style_variation": opening_mode,
        "opening_style": f"{opening_mode}，避免复用“听起来/我理解/我听见”式固定开头。",
        "correction_state": {
            "user_corrected_previous_reply": correction_type != "none",
            "correction_type": correction_type,
        },
        "psychologizing_risk": psychologizing_risk,
        "button_style": button_style,
        "risk_phase": risk_phase,
    }
