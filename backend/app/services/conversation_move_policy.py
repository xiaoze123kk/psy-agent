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
ANALYSIS_BOUNDARY_TERMS = (
    "别又开始分析我",
    "别分析我",
    "别分析",
    "不要分析我",
    "不要分析",
    "别心理分析",
    "不要心理分析",
    "别心理化",
    "不要心理化",
)
QUESTION_BOUNDARY_TERMS = (
    "别一直问",
    "不要一直问",
    "别老问",
    "不要老问",
    "别追问",
    "不要追问",
    "问题太多",
)
SAFETY_BOUNDARY_TERMS = ("别问安全", "别一直问安全", "别盘问安全", "不要问安全")
PAUSE_REQUEST_TERMS = ("就停在这儿", "就停在这里", "停在这儿吧", "停在这里吧", "先停在这", "到这儿吧", "到这里吧")
ADAPTATION_COUNT_KEYS = (
    "avoid_analysis_turns",
    "avoid_questions_turns",
    "avoid_safety_check_turns",
    "prefer_direct_anchor_response_turns",
)
NEGATIVE_EXPLICIT_FEEDBACK = {"missed", "too_analytic", "too_generic", "too_many_questions"}


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


def _recent_quoted_titles(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    titles: list[str] = []
    for message in messages[-8:]:
        content = str(message.get("content") or "")
        for title in re.findall(r"《([^》]{1,32})》", content):
            cleaned = title.strip()
            if cleaned and cleaned not in titles:
                titles.append(cleaned)
    return titles


def _recent_title_mentioned(text: str, messages: Sequence[Mapping[str, Any]]) -> str:
    compact = "".join(text.split())
    for title in reversed(_recent_quoted_titles(messages)):
        if title and title in compact:
            return title
    return ""


def _suppressed_recent_anchors(text: str, anchor_type: str, anchor_value: str, messages: Sequence[Mapping[str, Any]]) -> list[str]:
    if anchor_type != "none" or anchor_value or _is_short_followup(text):
        return []
    titles: list[str] = []
    for title in reversed(_recent_quoted_titles(messages)):
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= 3:
            break
    return titles


def _common_cultural_anchor(text: str) -> tuple[str, str]:
    compact = "".join(text.split()).strip("，。！？?；;：:")
    anchor_type = COMMON_CULTURAL_ANCHORS.get(compact, "")
    return (anchor_type, compact) if anchor_type else ("", "")


def _anchor_clue(text: str, kind: str, source: str = "current_user") -> dict[str, str]:
    return {"text": text, "kind": kind, "source": source}


def _dedupe_clues(clues: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
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


def _user_clues_for_anchor(text: str) -> list[dict[str, str]]:
    clues: list[dict[str, str]] = []
    compact = "".join(text.split())
    for term in KNOWLEDGE_BOUNDARY_TERMS:
        if term in text:
            clues.append(_anchor_clue(term, "knowledge_boundary"))
    for term in THEME_CLUE_TERMS:
        if term in text:
            clues.append(_anchor_clue(term, "theme"))
    if "记不清原句" in compact or "原句记不清" in compact:
        clues.append(_anchor_clue("记不清原句", "knowledge_boundary"))
        if "被什么东西推着走" in compact:
            clues.append(_anchor_clue("被什么东西推着走", "image"))
        elif "推着走" in compact:
            clues.append(_anchor_clue("推着走", "image"))
    return _dedupe_clues(clues)


def _clean_person_candidate(value: str) -> str:
    candidate = value.strip(" 　，。！？?：:；;、“”‘’《》")
    candidate = re.sub(r"(这个人|这个角色|这个作者|这位|是谁|吗|呢)$", "", candidate).strip()
    if (
        not candidate
        or candidate in GENERIC_PERSON_ANCHORS
        or len(candidate) > 12
        or any(mark in candidate for mark in "，。！？?；;：:、")
        or _has_any(candidate, ("安全", "分析", "建议", "感觉", "话题", "事情", "问题", "压力"))
    ):
        return ""
    return candidate


def _person_anchor_value(text: str) -> str:
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
        candidate = _clean_person_candidate(match.group("name"))
        if candidate:
            return candidate
    return ""


def _anchor_value(text: str, anchor_type: str, messages: Sequence[Mapping[str, Any]]) -> str:
    book_title = _extract_book_title(text)
    if book_title:
        return book_title
    recent_title = _recent_title_mentioned(text, messages)
    if recent_title:
        return recent_title
    _, common_anchor = _common_cultural_anchor(text)
    if common_anchor:
        return common_anchor
    person_anchor = _person_anchor_value(text)
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


def _topic_anchor_type(text: str, messages: Sequence[Mapping[str, Any]]) -> str:
    if _extract_book_title(text) or _recent_title_mentioned(text, messages):
        return "literary"
    common_anchor_type, _ = _common_cultural_anchor(text)
    if common_anchor_type:
        return common_anchor_type
    if _has_any(text, PHILOSOPHICAL_CONTEXT_TERMS):
        return "philosophical"
    if _has_any(text, MEDIA_TERMS):
        return "media"
    if _person_anchor_value(text):
        return "person"
    if _has_any(text, LITERARY_CONTEXT_TERMS):
        return "literary"
    if _has_any(text, DAILY_DETAIL_TERMS):
        return "daily_detail"
    if _has_any(text, METAPHOR_TERMS):
        return "metaphor"
    return "none"


def _cultural_response_mode(
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


def _anchor_evidence(
    text: str,
    anchor_type: str,
    anchor_value: str,
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    effective_type = anchor_type
    compact = "".join(text.split())
    if "记不清原句" in compact or "原句记不清" in compact:
        effective_type = "quote"
    elif effective_type == "none" and _has_any(text, KNOWLEDGE_BOUNDARY_TERMS):
        effective_type = "unknown_cultural"

    if effective_type == "none" and not anchor_value:
        return {}

    clues = _user_clues_for_anchor(text)
    recent_context_clues = [
        _anchor_clue(title, "recent_title", "recent_context")
        for title in _recent_quoted_titles(messages)
        if title and title != anchor_value
    ][:3]
    confidence = "explicit" if anchor_value or clues else "weak"
    mode = _cultural_response_mode(effective_type, anchor_value, clues, text)
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


def _matched_terms(text: str, terms: Sequence[str]) -> list[str]:
    compact = "".join(text.split())
    result: list[str] = []
    for term in terms:
        if not term or term not in compact or any(term in existing for existing in result):
            continue
        result = [existing for existing in result if existing not in term]
        result.append(term)
    return result


def _is_pause_request(text: str) -> bool:
    return bool(_matched_terms(text, PAUSE_REQUEST_TERMS))


def _wants_to_keep_anchor_light(text: str) -> bool:
    compact = "".join(text.split())
    return (
        ("不是想聊" in compact or "不想聊" in compact or "不是要聊" in compact)
        and ("本身" in compact or "作品" in compact or "情节" in compact)
    )


def _is_cultural_lane_anchor(anchor_type: str) -> bool:
    return anchor_type in CULTURAL_ANCHOR_TYPES or anchor_type == "metaphor"


def _latest_assistant_policy(messages: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping):
            policy = metadata.get("conversation_move_policy")
            if isinstance(policy, Mapping):
                return policy
        policy = message.get("conversation_move_policy")
        if isinstance(policy, Mapping):
            return policy
    return {}


def _quality_user_signal(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    quality_trace = payload.get("conversation_quality_trace")
    if isinstance(quality_trace, Mapping):
        user_signal = quality_trace.get("user_signal")
        if isinstance(user_signal, Mapping):
            return user_signal
    trace_summary = payload.get("trace_summary")
    if isinstance(trace_summary, Mapping):
        conversation_quality = trace_summary.get("conversation_quality")
        if isinstance(conversation_quality, Mapping):
            user_signal = conversation_quality.get("user_signal")
            if isinstance(user_signal, Mapping):
                return user_signal
    return {}


def _latest_assistant_explicit_feedback(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        candidates: list[object] = [message]
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.insert(0, metadata)
        for candidate in candidates:
            feedback = str(_quality_user_signal(candidate).get("explicit_feedback") or "").strip()
            if feedback:
                return feedback
    return "none"


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _adaptation_state_from_recent(
    messages: Sequence[Mapping[str, Any]],
    correction_type: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous_policy = _latest_assistant_policy(messages)
    explicit_feedback = _latest_assistant_explicit_feedback(messages)
    previous_raw = previous_policy.get("adaptation_state") if isinstance(previous_policy, Mapping) else None
    previous = previous_raw if isinstance(previous_raw, Mapping) else {}
    decayed: dict[str, Any] = {
        key: max(0, _nonnegative_int(previous.get(key)) - 1)
        for key in ADAPTATION_COUNT_KEYS
    }
    decayed["last_correction_type"] = str(previous.get("last_correction_type") or "none")

    notes: list[str] = []
    source = "recent_assistant_metadata" if previous else "none"
    if decayed["avoid_questions_turns"] > 0:
        notes.append("减少问句")
    if decayed["avoid_analysis_turns"] > 0:
        notes.append("降低分析深度")
    if decayed["avoid_safety_check_turns"] > 0:
        notes.append("减少安全盘问")
    if decayed["prefer_direct_anchor_response_turns"] > 0:
        notes.append("优先直接回应用户线索")

    if explicit_feedback in NEGATIVE_EXPLICIT_FEEDBACK:
        source = "explicit_feedback" if source == "none" else f"{source}+explicit_feedback"
        decayed["last_correction_type"] = f"feedback_{explicit_feedback}"
        if explicit_feedback == "too_analytic":
            decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 3)
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                2,
            )
            notes.extend(["根据用户反馈降低分析深度", "优先直接回应用户线索"])
        elif explicit_feedback == "too_many_questions":
            decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 3)
            notes.append("根据用户反馈减少问句")
        elif explicit_feedback == "too_generic":
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                2,
            )
            notes.append("根据用户反馈更具体地接住本轮线索")
        elif explicit_feedback == "missed":
            decayed["prefer_direct_anchor_response_turns"] = max(
                decayed["prefer_direct_anchor_response_turns"],
                3,
            )
            decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 1)
            notes.extend(["根据用户反馈重新选择主线", "优先直接回应用户线索"])

    if correction_type == "too_psychological":
        decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 3)
        decayed["prefer_direct_anchor_response_turns"] = max(decayed["prefer_direct_anchor_response_turns"], 3)
        decayed["last_correction_type"] = correction_type
        notes.extend(["降低分析深度", "优先直接回应用户线索"])
    elif correction_type == "too_many_questions":
        decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 3)
        decayed["last_correction_type"] = correction_type
        notes.append("减少问句")
    elif correction_type == "too_safety_focused":
        decayed["avoid_safety_check_turns"] = max(decayed["avoid_safety_check_turns"], 2)
        decayed["avoid_questions_turns"] = max(decayed["avoid_questions_turns"], 1)
        decayed["last_correction_type"] = correction_type
        notes.extend(["减少安全盘问", "减少问句"])
    elif correction_type == "not_that_meaning":
        decayed["prefer_direct_anchor_response_turns"] = max(decayed["prefer_direct_anchor_response_turns"], 3)
        decayed["avoid_analysis_turns"] = max(decayed["avoid_analysis_turns"], 1)
        decayed["last_correction_type"] = correction_type
        notes.extend(["重新选择主线", "降低分析深度"])

    compact = "".join(text.split())
    if (
        _has_any(compact, ("可以分析", "帮我分析", "分析一下", "展开分析"))
        and not _matched_terms(compact, ANALYSIS_BOUNDARY_TERMS)
    ):
        decayed["avoid_analysis_turns"] = 0
        notes.append("用户允许本轮分析")

    deduped_notes = list(dict.fromkeys(note for note in notes if note))
    delta = {
        "source": source,
        "applied_correction": correction_type if correction_type != "none" else "none",
        "notes": "；".join(deduped_notes),
    }
    return decayed, delta


def _intent_lanes_for(
    text: str,
    anchor_type: str,
    anchor_value: str,
    correction_type: str,
) -> tuple[str, list[dict[str, Any]]]:
    lanes: list[dict[str, Any]] = []
    self_clues = _matched_terms(text, SELF_REFERENCE_TERMS)
    analysis_boundary_clues = _matched_terms(text, ANALYSIS_BOUNDARY_TERMS)
    question_boundary_clues = _matched_terms(text, QUESTION_BOUNDARY_TERMS)
    safety_boundary_clues = _matched_terms(text, SAFETY_BOUNDARY_TERMS)
    keep_anchor_light = _wants_to_keep_anchor_light(text)

    if _is_cultural_lane_anchor(anchor_type) and anchor_value:
        priority = "secondary" if self_clues or keep_anchor_light else "primary"
        handling = "do_not_expand_work_detail" if keep_anchor_light or self_clues else "respond_to_anchor"
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "cultural_anchor",
                "anchor_type": anchor_type,
                "anchor_value": anchor_value,
                "priority": priority,
                "handling": handling,
            }
        )

    if self_clues:
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "self_reference",
                "user_clues": self_clues,
                "priority": "primary",
                "handling": "respond_to_user_clue",
            }
        )

    if analysis_boundary_clues or correction_type == "too_psychological":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": analysis_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "lower_analysis_depth",
            }
        )
    if question_boundary_clues or correction_type == "too_many_questions":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": question_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "reduce_questions",
            }
        )
    if safety_boundary_clues or correction_type == "too_safety_focused":
        lanes.append(
            {
                "id": f"lane_{len(lanes) + 1}",
                "kind": "boundary",
                "user_clues": safety_boundary_clues,
                "priority": "blocking_style_constraint",
                "handling": "avoid_safety_check",
            }
        )

    primary_lane = "quiet_presence" if _is_pause_request(text) else ""
    for lane in lanes:
        if lane.get("priority") == "primary":
            primary_lane = str(lane.get("kind") or primary_lane)
            break
    if not primary_lane:
        if correction_type != "none":
            primary_lane = "correction"
        elif lanes:
            primary_lane = str(lanes[0].get("kind") or "current_turn")
        else:
            primary_lane = "current_turn"
    return primary_lane, lanes


def _voice_contract_for(
    *,
    text: str,
    risk_level: str,
    conversation_move: str,
    correction_type: str,
    anchor_type: str,
    primary_lane: str,
    intent_lanes: Sequence[Mapping[str, Any]],
    adaptation_state: Mapping[str, Any],
) -> dict[str, Any]:
    has_blocking_boundary = any(
        str(lane.get("priority") or "") == "blocking_style_constraint" for lane in intent_lanes
    )
    if risk_level in HIGH_RISK_LEVELS:
        voice_mode = "safety_gentle"
    elif _is_pause_request(text):
        voice_mode = "quiet_presence"
    elif correction_type != "none":
        voice_mode = "correction_repair"
    elif primary_lane == "self_reference" or _is_cultural_lane_anchor(anchor_type):
        voice_mode = "anchored_companion"
    elif conversation_move == "ordinary_chat":
        voice_mode = "ordinary_chat"
    else:
        voice_mode = "quiet_presence" if len("".join(text.split())) <= 12 else "anchored_companion"

    analysis_depth = "light"
    if voice_mode in {"quiet_presence", "safety_gentle"}:
        analysis_depth = "none"
    elif voice_mode == "ordinary_chat":
        analysis_depth = "none"
    elif correction_type == "too_psychological" or adaptation_state.get("avoid_analysis_turns", 0) > 0:
        analysis_depth = "none"
    elif has_blocking_boundary:
        analysis_depth = "none"

    question_budget = 1
    if voice_mode == "quiet_presence" or has_blocking_boundary:
        question_budget = 0
    if adaptation_state.get("avoid_questions_turns", 0) > 0:
        question_budget = 0
    if correction_type in {"too_many_questions", "too_psychological"}:
        question_budget = 0
    if risk_level in HIGH_RISK_LEVELS:
        question_budget = 1

    sentence_budget = "2-4"
    if voice_mode == "quiet_presence":
        sentence_budget = "1-2"
    elif voice_mode == "safety_gentle":
        sentence_budget = "1-3"
    elif conversation_move == "ordinary_chat":
        sentence_budget = "1-3"

    opening_preference = "direct"
    if voice_mode in {"ordinary_chat", "quiet_presence", "correction_repair"}:
        opening_preference = "no_preface"
    elif primary_lane in {"self_reference", "cultural_anchor"}:
        opening_preference = "echo_user_words"

    closing_preference = "soft_invitation" if question_budget > 0 else "pause"
    if voice_mode == "safety_gentle":
        closing_preference = "micro_action"

    return {
        "voice_mode": voice_mode,
        "analysis_depth": analysis_depth,
        "question_budget": question_budget,
        "sentence_budget": sentence_budget,
        "opening_preference": opening_preference,
        "closing_preference": closing_preference,
        "humor_allowed": voice_mode == "ordinary_chat",
        "avoid_patterns": ["听起来你", "这说明你", "你可能是在"],
    }


def _recent_assistant_opening_mode(messages: Sequence[Mapping[str, Any]]) -> str:
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


def _recent_assistant_contents(messages: Sequence[Mapping[str, Any]], *, limit: int = 3) -> list[str]:
    contents: list[str] = []
    for message in messages:
        if str(message.get("role") or "") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            contents.append(content)
    return contents[-limit:]


def _reply_structure_signature(text: str) -> str:
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
    if question_count == 0 and _has_any(stripped, ("先停", "放在这里", "不用急着", "不推进", "停一会儿")):
        return "pause_then_invite"
    if len(paragraphs) <= 1:
        return "single_paragraph"
    return "multi_paragraph"


def _recent_reused_structure(messages: Sequence[Mapping[str, Any]]) -> str:
    signatures = [
        _reply_structure_signature(content)
        for content in _recent_assistant_contents(messages)
    ]
    signatures = [
        signature
        for signature in signatures
        if signature in {"two_beat_question", "single_paragraph", "brief_answer", "pause_then_invite"}
    ]
    if len(signatures) >= 2 and signatures[-1] == signatures[-2]:
        return signatures[-1]
    return ""


def _base_structure_mode(conversation_move: str, text: str) -> str:
    compact = "".join(text.split())
    if conversation_move == "micro_step":
        return "brief_answer"
    if conversation_move == "ordinary_chat":
        if len(compact) <= 20 or _has_any(text, LIGHT_CHAT_TERMS):
            return "brief_answer"
        return "single_paragraph"
    if conversation_move in {"continue_thread", "respond_to_anchor", "post_risk_return", "correction_followup"}:
        return "single_paragraph"
    if conversation_move == "soft_invitation":
        return "pause_then_invite"
    return "single_paragraph"


def _structure_mode_for(conversation_move: str, text: str, messages: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    base = _base_structure_mode(conversation_move, text)
    avoid_structure = _recent_reused_structure(messages)
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


def _structure_style(mode: str, avoid_structure: str) -> str:
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
    anchor_type = _topic_anchor_type(text, messages)
    anchor_value = _anchor_value(text, anchor_type, messages)
    anchor_evidence = _anchor_evidence(text, anchor_type, anchor_value, messages)
    if anchor_type == "none" and anchor_evidence:
        anchor_type = str(anchor_evidence.get("anchor_type") or anchor_type)
    suppressed_recent_anchors = _suppressed_recent_anchors(text, anchor_type, anchor_value, messages)
    recent_high_risk = _recent_high_risk_seen(messages)
    adaptation_state, adaptation_state_delta = _adaptation_state_from_recent(messages, correction_type, text)
    primary_lane, intent_lanes = _intent_lanes_for(text, anchor_type, anchor_value, correction_type)

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
    elif _is_pause_request(text):
        conversation_move = "soft_invitation"
        button_style = "user_voice"
        psychologizing_risk = "low"
        anchor_handling = "avoid_psychologizing"
        handling = "尊重用户想停在这里的边界，安静收住；不总结、不分析、不追问。"
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
    elif anchor_type in {"literary", "philosophical", "media", "person", "metaphor", "quote", "concept", "unknown_cultural"}:
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

    structure_mode, avoid_structure = _structure_mode_for(conversation_move, text, messages)
    voice_contract = _voice_contract_for(
        text=text,
        risk_level=risk_level,
        conversation_move=conversation_move,
        correction_type=correction_type,
        anchor_type=anchor_type,
        primary_lane=primary_lane,
        intent_lanes=intent_lanes,
        adaptation_state=adaptation_state,
    )

    return {
        "conversation_move": conversation_move,
        "intent_lanes": intent_lanes,
        "primary_lane": primary_lane,
        "ningyu_voice_contract": voice_contract,
        "adaptation_state": adaptation_state,
        "adaptation_state_delta": adaptation_state_delta,
        "topic_anchor": anchor_type,
        "anchor_value": anchor_value,
        "anchor_handling": anchor_handling,
        "anchor_evidence": anchor_evidence,
        "cultural_response_mode": anchor_evidence.get("response_mode", ""),
        "suppressed_recent_anchors": suppressed_recent_anchors,
        "stale_anchor_handling": (
            "最近出现过这些锚点，但用户本轮没有主动提；不要主动带回，除非用户再次提到。"
            if suppressed_recent_anchors
            else ""
        ),
        "handling": handling,
        "style_variation": opening_mode,
        "opening_style": f"{opening_mode}，避免复用“听起来/我理解/我听见”式固定开头。",
        "structure_mode": structure_mode,
        "structure_style": _structure_style(structure_mode, avoid_structure),
        "avoid_structure": avoid_structure,
        "avoid_reused_structure": bool(avoid_structure),
        "correction_state": {
            "user_corrected_previous_reply": correction_type != "none",
            "correction_type": correction_type,
        },
        "psychologizing_risk": psychologizing_risk,
        "button_style": button_style,
        "risk_phase": risk_phase,
    }
