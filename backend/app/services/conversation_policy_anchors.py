from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}

LITERARY_CONTEXT_TERMS = ("文学", "小说", "书", "作品", "诗", "作者", "文本")
PHILOSOPHICAL_CONTEXT_TERMS = ("哲学", "哲学家", "存在主义", "原型", "阴影", "潜意识")
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
    "情绪不好",
    "心情不好",
    "生气",
    "愤怒",
    "火大",
    "委屈",
    "不想活",
    "想死",
)
SHORT_FOLLOWUP_TERMS = ("记得", "嗯", "嗯嗯", "是这个", "对", "就是", "继续", "然后呢")
GENERIC_PERSON_ANCHORS = {
    "点别的",
    "别的",
    "这个",
    "这件事",
    "这事",
    "一下",
    "安全",
    "自己",
    "我",
    "你",
    "他",
    "她",
}
CULTURAL_ANCHOR_TYPES = {
    "literary",
    "philosophical",
    "media",
    "person",
    "quote",
    "concept",
    "unknown_cultural",
}
KNOWLEDGE_BOUNDARY_TERMS = (
    "没读过",
    "没看过",
    "只是听说",
    "听别人说",
    "不确定",
    "记不清",
    "不知道准不准",
)
THEME_CLUE_TERMS = (
    "自我寻找",
    "找自己",
    "阴影",
    "梦",
    "象征",
    "意义",
    "被规训",
    "被推着走",
    "慢半拍",
)
COMMON_CULTURAL_ANCHORS = {
    "在轮下": "literary",
    "德米安": "literary",
    "悉达多": "literary",
    "荒原狼": "literary",
    "局外人": "literary",
    "人间失格": "literary",
    "荣格": "philosophical",
    "弗洛伊德": "philosophical",
    "尼采": "philosophical",
    "加缪": "philosophical",
    "萨特": "philosophical",
    "黑塞": "person",
    "卡夫卡": "person",
}
SELF_REFERENCE_TERMS = ("找自己", "自我寻找", "有点像我", "像我", "跟我很像", "和我很像")


def text_from_state(state: Mapping[str, Any]) -> str:
    return str(state.get("normalized_text") or state.get("user_text") or "")


def has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def recent_messages(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = state.get("recent_messages")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [message for message in raw if isinstance(message, Mapping)]


def recent_high_risk_seen(messages: Sequence[Mapping[str, Any]]) -> bool:
    for message in messages[-6:]:
        if str(message.get("risk_level") or "") in HIGH_RISK_LEVELS:
            return True
    return False


def extract_book_title(text: str) -> str:
    start = text.find("《")
    end = text.find("》", start + 1)
    if start >= 0 and end > start:
        return text[start + 1 : end].strip()
    return ""


def recent_quoted_titles(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    titles: list[str] = []
    for message in messages[-8:]:
        content = str(message.get("content") or "")
        for title in re.findall(r"《([^》]{1,32})》", content):
            cleaned = title.strip()
            if cleaned and cleaned not in titles:
                titles.append(cleaned)
    return titles


def recent_title_mentioned(text: str, messages: Sequence[Mapping[str, Any]]) -> str:
    compact = "".join(text.split())
    for title in reversed(recent_quoted_titles(messages)):
        if title and title in compact:
            return title
    return ""


def suppressed_recent_anchors(
    text: str,
    anchor_type: str,
    anchor_value: str,
    messages: Sequence[Mapping[str, Any]],
) -> list[str]:
    if anchor_type != "none" or anchor_value or is_short_followup(text):
        return []
    titles: list[str] = []
    for title in reversed(recent_quoted_titles(messages)):
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= 3:
            break
    return titles


def common_cultural_anchor(text: str) -> tuple[str, str]:
    compact = "".join(text.split()).strip("，。！？?；;：:")
    anchor_type = COMMON_CULTURAL_ANCHORS.get(compact, "")
    return (anchor_type, compact) if anchor_type else ("", "")


def anchor_clue(text: str, kind: str, source: str = "current_user") -> dict[str, str]:
    return {"text": text, "kind": kind, "source": source}


def dedupe_clues(clues: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for clue in clues:
        text = str(clue.get("text") or "").strip()
        kind = str(clue.get("kind") or "").strip()
        source = str(clue.get("source") or "current_user").strip()
        key = (text, kind)
        if not text or not kind or key in seen:
            continue
        seen.add(key)
        result.append({"text": text, "kind": kind, "source": source})
    return result


def user_clues_for_anchor(text: str) -> list[dict[str, str]]:
    clues: list[dict[str, str]] = []
    compact = "".join(text.split())
    for term in KNOWLEDGE_BOUNDARY_TERMS:
        if term in text:
            clues.append(anchor_clue(term, "knowledge_boundary"))
    for term in THEME_CLUE_TERMS:
        if term in text:
            clues.append(anchor_clue(term, "theme"))
    if "记不清原句" in compact or "原句记不清" in compact:
        clues.append(anchor_clue("记不清原句", "knowledge_boundary"))
        if "被什么东西推着走" in compact:
            clues.append(anchor_clue("被什么东西推着走", "image"))
        elif "推着走" in compact:
            clues.append(anchor_clue("推着走", "image"))
    return dedupe_clues(clues)


def clean_person_candidate(value: str) -> str:
    candidate = value.strip(" 　，。！？?：:；;、“”‘’《》")
    candidate = re.sub(r"(这个人|这个角色|这个作者|这位|是谁|吗|呢)$", "", candidate).strip()
    if (
        not candidate
        or candidate in GENERIC_PERSON_ANCHORS
        or len(candidate) > 12
        or any(mark in candidate for mark in "，。！？?；;：:、")
        or has_any(candidate, ("安全", "分析", "建议", "感觉", "话题", "事情", "问题", "压力"))
    ):
        return ""
    return candidate


def person_anchor_value(text: str) -> str:
    patterns = (
        r"你觉得(?P<name>[^，。！？?；;：:\s]{2,12})是(?:个|一个|一位)?什么样的人",
        r"(?P<name>[^，。！？?；;：:\s]{2,12})是(?:个|一个|一位)?什么样的人",
        r"(?:我想聊|想聊聊|想聊|聊聊|先聊|说说|谈谈)(?P<name>[^，。！？?；;：:\s]{2,12})",
        r"关于(?P<name>[^，。！？?；;：:\s]{2,12})这个人",
        r"(?P<name>[^，。！？?；;：:\s]{2,12})这个人",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = clean_person_candidate(match.group("name"))
        if candidate:
            return candidate
    return ""


def anchor_value(text: str, anchor_type: str, messages: Sequence[Mapping[str, Any]]) -> str:
    book_title = extract_book_title(text)
    if book_title:
        return book_title
    recent_title = recent_title_mentioned(text, messages)
    if recent_title:
        return recent_title
    _, common_anchor = common_cultural_anchor(text)
    if common_anchor:
        return common_anchor
    person_anchor = person_anchor_value(text)
    if person_anchor:
        return person_anchor
    for terms in (LITERARY_CONTEXT_TERMS, PHILOSOPHICAL_CONTEXT_TERMS, MEDIA_TERMS, DAILY_DETAIL_TERMS):
        for term in terms:
            if term and term in text:
                return term
    if anchor_type == "metaphor":
        for term in METAPHOR_TERMS:
            if term in text:
                return term
    return ""


def topic_anchor_type(text: str, messages: Sequence[Mapping[str, Any]]) -> str:
    if extract_book_title(text) or recent_title_mentioned(text, messages):
        return "literary"
    common_anchor_type, _ = common_cultural_anchor(text)
    if common_anchor_type:
        return common_anchor_type
    if has_any(text, PHILOSOPHICAL_CONTEXT_TERMS):
        return "philosophical"
    if has_any(text, MEDIA_TERMS):
        return "media"
    if person_anchor_value(text):
        return "person"
    if has_any(text, LITERARY_CONTEXT_TERMS):
        return "literary"
    if has_any(text, DAILY_DETAIL_TERMS):
        return "daily_detail"
    if has_any(text, METAPHOR_TERMS):
        return "metaphor"
    return "none"


def cultural_response_mode(
    anchor_type: str,
    anchor_value: str,
    clues: Sequence[Mapping[str, str]],
    text: str,
) -> str:
    if anchor_type not in CULTURAL_ANCHOR_TYPES:
        return ""
    clue_kinds = {str(clue.get("kind") or "") for clue in clues}
    if "knowledge_boundary" in clue_kinds and anchor_type in {"quote", "unknown_cultural"}:
        return "no_knowledge_claim"
    if "knowledge_boundary" in clue_kinds or "theme" in clue_kinds or "image" in clue_kinds:
        return "echo_user_clue"
    if anchor_value in COMMON_CULTURAL_ANCHORS:
        return "light_context_only"
    if anchor_type in {"person", "concept"} and anchor_value:
        return "ask_user_association"
    if anchor_type in {"philosophical", "literary", "media"} and anchor_value:
        return "light_context_only"
    return "ask_user_association"


def anchor_evidence(
    text: str,
    anchor_type: str,
    anchor_value: str,
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    effective_type = anchor_type
    compact = "".join(text.split())
    if "记不清原句" in compact or "原句记不清" in compact:
        effective_type = "quote"
    elif effective_type == "none" and has_any(text, KNOWLEDGE_BOUNDARY_TERMS):
        effective_type = "unknown_cultural"

    if effective_type == "none" and not anchor_value:
        return {}

    clues = user_clues_for_anchor(text)
    recent_context_clues = [
        anchor_clue(title, "recent_title", "recent_context")
        for title in recent_quoted_titles(messages)
        if title and title != anchor_value
    ][:3]
    confidence = "explicit" if anchor_value or clues else "weak"
    mode = cultural_response_mode(effective_type, anchor_value, clues, text)
    allowed_basis = ["user_clues", "recent_context"]
    if mode == "light_context_only":
        allowed_basis.append("light_common_sense")

    return {
        "anchor_type": effective_type,
        "anchor_value": anchor_value,
        "confidence": confidence,
        "user_clues": clues,
        "recent_context_clues": recent_context_clues,
        "allowed_basis": allowed_basis,
        "forbidden_claims": [
            "plot_detail",
            "character_detail",
            "author_intent",
            "ending",
            "quote_attribution",
        ],
        "response_mode": mode,
    }


def is_cultural_lane_anchor(anchor_type: str) -> bool:
    return anchor_type in CULTURAL_ANCHOR_TYPES or anchor_type == "metaphor"


def is_short_followup(text: str) -> bool:
    compact = "".join(text.split())
    return compact in SHORT_FOLLOWUP_TERMS or (len(compact) <= 4 and has_any(compact, SHORT_FOLLOWUP_TERMS))
