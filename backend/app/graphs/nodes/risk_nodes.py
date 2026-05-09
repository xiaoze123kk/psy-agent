from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal, TypedDict, cast

from app.core.config import settings
from app.graphs.nodes.common import AgentState, contains_any, matched_keywords
from app.services.deepseek_client import deepseek_client


logger = logging.getLogger(__name__)

Timeframe = Literal["none", "vague", "near_term"]


class SemanticRiskSignals(TypedDict):
    ideation: bool
    intent: bool
    plan: bool
    means: bool
    timeframe: Timeframe
    protective_factor: bool
    ambiguity: float
    discussion_context: bool
    third_party_context: bool


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
        "不想再醒来",
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

IMPLICIT_FAREWELL_TERMS = (
    "安排好后事",
    "后事安排",
    "后事都安排",
    "东西都交代",
    "都交代好了",
    "交代完了",
    "把东西都送人",
    "东西都送人",
    "最后一次聊天",
    "最后一次和你说",
    "可能这是最后一次",
    "撑不到明天",
    "不想再醒来",
)
NEAR_TERM_TERMS = (
    "今晚",
    "今天",
    "明天",
    "现在",
    "立刻",
    "马上",
    "这会儿",
    "等下",
    "一会儿",
    "right now",
    "tonight",
    "today",
    "tomorrow",
)
MEANS_TERMS = (
    "刀",
    "药",
    "一瓶药",
    "手里",
    "楼顶",
    "跳楼",
    "跳下去",
    "绳",
    "煤气",
    "knife",
    "pills",
    "roof",
    "bridge",
)
PLAN_DETAIL_TERMS = (
    "遗书",
    "准备好了",
    "已经准备",
    "准备了",
    "安排好",
    "交代好",
    "存了一瓶",
    "打算",
    "计划",
    "plan",
)
INTENT_TERMS = (
    "打算",
    "决定",
    "准备",
    "就要",
    "要去",
    "马上",
    "立刻",
    "intend",
    "going to",
    "need to",
)
PROTECTIVE_FACTOR_TERMS = (
    "不会做",
    "不会真的",
    "不会伤害自己",
    "没有计划",
    "没计划",
    "朋友在旁边",
    "朋友在",
    "家人在",
    "有人陪",
    "我会联系",
    "我能联系",
    "won't do it",
    "not going to do it",
    "with me",
    "safe right now",
)
ACADEMIC_CONTEXT_TERMS = (
    "论文",
    "研究",
    "新闻",
    "课程",
    "课堂",
    "作业",
    "文献",
    "教材",
    "报告",
    "案例分析",
    "风险评估",
    "预防热线",
    "采访",
    "电影",
    "小说",
    "讨论",
    "提到",
    "讲到",
    "分析",
    "paper",
    "research",
    "news",
    "case study",
)
THIRD_PARTY_CONTEXT_TERMS = (
    "里面有人",
    "有人说",
    "朋友说",
    "同学说",
    "患者说",
    "来访者说",
    "案例里",
    "新闻里",
    "he said",
    "she said",
    "someone said",
)
DIRECT_PERSONAL_RISK_TERMS = (
    "我想自杀",
    "我要自杀",
    "我打算自杀",
    "我准备自杀",
    "我想结束生命",
    "我今晚结束生命",
    "我不想活",
    "我不想活了",
    "我想去死",
    "我想伤害自己",
    "我控制不住想伤害自己",
    "我最近总想到自杀",
    "我想到自杀",
    "自己想自杀",
    "自己没救",
    "我已经安排好后事",
    "我把东西都送人",
    "我不想醒来",
    "我不想再醒来",
    "我撑不下去",
    "我活不下去",
    "i want to die",
    "i want to kill myself",
    "i need to end my life",
    "i should kill myself",
    "kill myself",
    "hurt myself",
)


def _unique(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _default_semantic_risk() -> SemanticRiskSignals:
    return {
        "ideation": False,
        "intent": False,
        "plan": False,
        "means": False,
        "timeframe": "none",
        "protective_factor": False,
        "ambiguity": 0.0,
        "discussion_context": False,
        "third_party_context": False,
    }


def _keyword_stage(text: str) -> dict[str, object]:
    lowered = (text or "").lower()
    suicide_matches = matched_keywords(lowered, RISK_KEYWORDS["suicide_terms"])
    plan_matches = matched_keywords(lowered, RISK_KEYWORDS["plan_terms"])
    l2_matches = matched_keywords(lowered, RISK_KEYWORDS["l2_keywords"])
    l1_matches = matched_keywords(lowered, RISK_KEYWORDS["l1_keywords"])

    reason_codes: list[str] = []
    if suicide_matches:
        reason_codes.append("explicit_ideation")
    if plan_matches:
        reason_codes.append("plan_or_means_keyword")
    if l2_matches:
        reason_codes.append("ambiguous_self_harm_signal")
    if l1_matches:
        reason_codes.append("elevated_distress")

    if suicide_matches and plan_matches:
        risk_level = "L3"
        reasons = suicide_matches + plan_matches
    elif l2_matches or suicide_matches:
        risk_level = "L2"
        reasons = l2_matches + suicide_matches
    elif l1_matches:
        risk_level = "L1"
        reasons = l1_matches
    else:
        risk_level = "L0"
        reasons = []

    return {
        "risk_level": risk_level,
        "risk_reasons": _unique(reasons)[:4],
        "risk_reason_codes": _unique(reason_codes),
    }


def semantic_risk_assess(text: str) -> tuple[SemanticRiskSignals, list[str], list[str]]:
    lowered = (text or "").lower()
    signals = _default_semantic_risk()

    suicide_matches = matched_keywords(lowered, RISK_KEYWORDS["suicide_terms"])
    l2_matches = matched_keywords(lowered, RISK_KEYWORDS["l2_keywords"])
    l1_matches = matched_keywords(lowered, RISK_KEYWORDS["l1_keywords"])
    implicit_matches = matched_keywords(lowered, IMPLICIT_FAREWELL_TERMS)
    near_term_matches = matched_keywords(lowered, NEAR_TERM_TERMS)
    means_matches = matched_keywords(lowered, MEANS_TERMS)
    plan_matches = matched_keywords(lowered, PLAN_DETAIL_TERMS)
    intent_matches = matched_keywords(lowered, INTENT_TERMS)
    protective_matches = matched_keywords(lowered, PROTECTIVE_FACTOR_TERMS)
    academic_matches = matched_keywords(lowered, ACADEMIC_CONTEXT_TERMS)
    third_party_matches = matched_keywords(lowered, THIRD_PARTY_CONTEXT_TERMS)

    direct_personal_risk = contains_any(lowered, DIRECT_PERSONAL_RISK_TERMS)
    discussion_context = bool(academic_matches or third_party_matches)
    non_personal_discussion = discussion_context and not direct_personal_risk
    reason_codes: list[str] = []
    reasons: list[str] = []

    if academic_matches:
        reason_codes.append("academic_context")
        reasons.extend(academic_matches[:2])
    if third_party_matches:
        reason_codes.append("third_party_context")
        reasons.extend(third_party_matches[:2])

    if non_personal_discussion:
        signals.update(
            {
                "ambiguity": 0.1,
                "discussion_context": True,
                "third_party_context": bool(third_party_matches),
            }
        )
        return signals, _unique(reason_codes), _unique(reasons)

    if suicide_matches:
        signals["ideation"] = True
        reason_codes.append("explicit_ideation")
        reasons.extend(suicide_matches[:3])
    if l2_matches:
        signals["ideation"] = True
        reason_codes.append("ambiguous_self_harm_signal")
        reasons.extend(l2_matches[:3])
    if implicit_matches:
        signals["ideation"] = True
        signals["plan"] = True
        reason_codes.append("implicit_farewell")
        reasons.extend(implicit_matches[:3])
    if intent_matches and signals["ideation"]:
        signals["intent"] = True
        reason_codes.append("intent_signal")
        reasons.extend(intent_matches[:2])
    if plan_matches and signals["ideation"]:
        signals["plan"] = True
        reason_codes.append("plan_signal")
        reasons.extend(plan_matches[:2])
    if means_matches:
        signals["means"] = True
        reason_codes.append("means_mentioned")
        reasons.extend(means_matches[:2])
    if near_term_matches:
        signals["timeframe"] = "near_term"
        reason_codes.append("near_term_timeframe")
        reasons.extend(near_term_matches[:2])
    elif signals["ideation"] or signals["plan"] or signals["intent"]:
        signals["timeframe"] = "vague"
    if protective_matches:
        signals["protective_factor"] = True
        reason_codes.append("protective_support_present")
        reasons.extend(protective_matches[:2])
    if l1_matches and not signals["ideation"]:
        reason_codes.append("elevated_distress")
        reasons.extend(l1_matches[:3])

    if implicit_matches and not suicide_matches and not l2_matches and not means_matches:
        signals["ambiguity"] = 0.62
    elif l2_matches and not suicide_matches and not means_matches:
        signals["ambiguity"] = 0.48
    elif signals["protective_factor"]:
        signals["ambiguity"] = 0.35
    elif signals["ideation"]:
        signals["ambiguity"] = 0.2
    elif l1_matches:
        signals["ambiguity"] = 0.15
    else:
        signals["ambiguity"] = 0.0

    signals["discussion_context"] = discussion_context
    signals["third_party_context"] = bool(third_party_matches)
    return signals, _unique(reason_codes), _unique(reasons)


def _level_from_signals(keyword_level: str, signals: SemanticRiskSignals, reason_codes: list[str]) -> str:
    if signals["discussion_context"] and not signals["ideation"]:
        return "L0"
    if keyword_level == "L3":
        return "L3"
    if signals["ideation"] and signals["means"]:
        return "L3"
    if signals["ideation"] and signals["timeframe"] == "near_term" and (
        signals["intent"] or signals["plan"] or "explicit_ideation" in reason_codes
    ):
        return "L3"
    if signals["ideation"] or keyword_level == "L2":
        return "L2"
    if "elevated_distress" in reason_codes or keyword_level == "L1":
        return "L1"
    return "L0"


def _risk_source(keyword_level: str, final_level: str, reason_codes: list[str]) -> str:
    semantic_codes = {
        "implicit_farewell",
        "academic_context",
        "third_party_context",
        "protective_support_present",
        "near_term_timeframe",
        "means_mentioned",
        "plan_signal",
        "intent_signal",
    }
    if final_level != keyword_level:
        return "semantic_rule"
    if semantic_codes.intersection(reason_codes):
        return "combined" if keyword_level != "L0" else "semantic_rule"
    return "keyword"


def _assessment_from_parts(
    text: str,
    *,
    semantic_risk: SemanticRiskSignals | None = None,
    semantic_reason_codes: list[str] | None = None,
    semantic_reasons: list[str] | None = None,
    risk_source_override: str | None = None,
) -> dict[str, object]:
    keyword = _keyword_stage(text)
    signals = semantic_risk
    reason_codes = semantic_reason_codes
    reasons = semantic_reasons
    if signals is None or reason_codes is None or reasons is None:
        signals, reason_codes, reasons = semantic_risk_assess(text)

    keyword_level = str(keyword["risk_level"])
    combined_codes = _unique(list(keyword["risk_reason_codes"]) + reason_codes)
    level = _level_from_signals(keyword_level, signals, combined_codes)
    combined_reasons = _unique(list(keyword["risk_reasons"]) + reasons)
    risk_reasons = [] if level == "L0" else combined_reasons[:4]
    requires_safety_check = level in {"L2", "L3"} or (
        signals["ideation"] and float(signals["ambiguity"]) >= 0.55 and not signals["discussion_context"]
    )

    return {
        "risk_level": level,
        "risk_reasons": risk_reasons,
        "semantic_risk": signals,
        "risk_reason_codes": combined_codes,
        "requires_safety_check": requires_safety_check,
        "risk_source": risk_source_override or _risk_source(keyword_level, level, combined_codes),
    }


def classify_risk_text(text: str) -> dict[str, object]:
    return _assessment_from_parts(text)


def sync_risk_classify(text: str) -> str:
    return str(classify_risk_text(text)["risk_level"])


def _coerce_bool(value: object) -> bool:
    return bool(value) if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes"}


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_llm_signals(value: object) -> SemanticRiskSignals | None:
    if not isinstance(value, dict):
        return None
    timeframe = str(value.get("timeframe") or "none").strip()
    if timeframe not in {"none", "vague", "near_term"}:
        timeframe = "none"
    timeframe_value = cast(Timeframe, timeframe)
    return {
        "ideation": _coerce_bool(value.get("ideation")),
        "intent": _coerce_bool(value.get("intent")),
        "plan": _coerce_bool(value.get("plan")),
        "means": _coerce_bool(value.get("means")),
        "timeframe": timeframe_value,
        "protective_factor": _coerce_bool(value.get("protective_factor")),
        "ambiguity": max(0.0, min(1.0, _coerce_float(value.get("ambiguity")))),
        "discussion_context": _coerce_bool(value.get("discussion_context")),
        "third_party_context": _coerce_bool(value.get("third_party_context")),
    }


def _parse_json_object(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _maybe_refine_with_llm(text: str, assessment: dict[str, object]) -> dict[str, object]:
    if not settings.risk_semantic_llm_enabled:
        return assessment
    semantic_risk = assessment.get("semantic_risk")
    if not isinstance(semantic_risk, dict):
        return assessment
    ambiguity = _coerce_float(semantic_risk.get("ambiguity"))
    if ambiguity < 0.55 and assessment.get("risk_level") not in {"L2", "L3"}:
        return assessment

    system_prompt = (
        "You are a safety classifier. Return only compact JSON with: ideation, intent, plan, means, "
        "timeframe(none|vague|near_term), protective_factor, ambiguity, discussion_context, third_party_context."
    )
    user_prompt = f"Classify this user message for self-harm risk signals:\n{text}"
    try:
        reply = await asyncio.wait_for(
            deepseek_client.chat(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0,
                max_tokens=220,
            ),
            timeout=max(settings.risk_semantic_llm_timeout_seconds, 0.1),
        )
    except Exception as exc:  # pragma: no cover - optional external path
        logger.warning("Risk semantic LLM refinement failed: %s", exc)
        return assessment
    if not reply:
        return assessment
    parsed = _parse_json_object(reply)
    refined_signals = _coerce_llm_signals(parsed)
    if refined_signals is None:
        return assessment
    reason_codes = list(assessment.get("risk_reason_codes") or [])
    if refined_signals["discussion_context"]:
        reason_codes.append("academic_context")
    if refined_signals["third_party_context"]:
        reason_codes.append("third_party_context")
    return _assessment_from_parts(
        text,
        semantic_risk=refined_signals,
        semantic_reason_codes=_unique(reason_codes),
        semantic_reasons=list(assessment.get("risk_reasons") or []),
        risk_source_override="semantic_llm",
    )


async def risk_classifier(state: AgentState) -> AgentState:
    text = state.get("normalized_text", "")
    assessment = await _maybe_refine_with_llm(text, classify_risk_text(text))
    risk_level = str(assessment["risk_level"])
    result: AgentState = {
        "risk_level": risk_level,  # type: ignore[typeddict-item]
        "risk_reasons": list(assessment.get("risk_reasons") or []),
        "semantic_risk": dict(assessment.get("semantic_risk") or {}),
        "risk_source": str(assessment.get("risk_source") or "keyword"),
        "risk_reason_codes": list(assessment.get("risk_reason_codes") or []),
        "requires_safety_check": bool(assessment.get("requires_safety_check")),
    }
    if risk_level in {"L2", "L3"}:
        result["intent"] = "crisis"
    return result


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
