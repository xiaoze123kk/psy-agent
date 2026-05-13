from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any

from sqlalchemy import desc, false, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    ConversationThread,
    MemoryConsolidationRun,
    MemoryEmbedding,
    MemoryOperation,
    MoodLog,
    User,
    UserMemory,
    utcnow,
)
from app.services.embedding_service import embedding_client
from app.services.milvus_service import milvus_store


logger = logging.getLogger(__name__)


VISIBLE_MEMORY_TYPES = {
    "profile",
    "correction",
    "preference",
    "session_summary",
    "recurring_trigger",
    "support_strategy",
    "relationship",
    "state",
    "goal",
}
INTERNAL_MEMORY_TYPES = {"safety_summary"}
ALL_MEMORY_TYPES = VISIBLE_MEMORY_TYPES | INTERNAL_MEMORY_TYPES
MEMORY_VECTOR_UPSERT_MAX_ATTEMPTS = 3

MEMORY_TYPE_LABELS = {
    "profile": "基础画像",
    "correction": "纠错偏好",
    "session_summary": "对话摘要",
    "preference": "陪伴偏好",
    "recurring_trigger": "触发点",
    "support_strategy": "支持方式",
    "relationship": "关系记忆",
    "state": "长期状态",
    "goal": "小目标",
    "safety_summary": "安全摘要",
}

MEMORY_TYPE_ORDER = [
    "profile",
    "correction",
    "preference",
    "session_summary",
    "recurring_trigger",
    "support_strategy",
    "relationship",
    "state",
    "goal",
    "safety_summary",
]

TYPE_PRIORITY = {memory_type: index for index, memory_type in enumerate(MEMORY_TYPE_ORDER)}

UNSAFE_VISIBLE_TERMS = (
    "确诊",
    "诊断",
    "抑郁症",
    "双相",
    "精神分裂",
    "人格障碍",
    "创伤后应激障碍",
    "ptsd",
    "用药",
    "药物剂量",
    "处方",
    "自杀",
    "自残",
    "结束生命",
    "不想活",
    "身份证",
    "银行卡",
    "手机号",
    "住址",
)

TAG_KEYWORDS = {
    "焦虑": ("焦虑", "心慌", "担心", "紧张"),
    "低落": ("低落", "难过", "崩溃", "委屈"),
    "睡眠": ("睡眠", "失眠", "睡不着", "熬夜"),
    "压力": ("压力", "考试", "工作", "学习", "任务"),
    "关系": ("朋友", "家人", "同学", "伴侣", "恋人", "关系"),
    "支持方式": ("呼吸", "练习", "陪", "安抚", "梳理", "倾听"),
    "纠错": ("不要", "别", "纠正", "先听", "听我说", "不喜欢", "不是这个意思"),
}

CORRECTION_SIGNAL_TERMS = (
    "不要",
    "别",
    "纠正",
    "先听",
    "听我说",
    "不是",
    "不喜欢",
    "先帮我",
    "别直接",
    "不要直接",
)
CONFLICT_MEMORY_TYPES = {"preference", "support_strategy"}
CONFLICT_TOPIC_TERMS = (
    "直接",
    "模板",
    "建议",
    "分析",
    "提问",
    "追问",
    "安抚",
    "倾听",
    "先听",
    "梳理",
    "边界",
    "步骤",
    "节奏",
)


def _clean_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    if limit is not None and len(text) > limit:
        return text[: max(limit - 1, 0)] + "…"
    return text


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_memory_type(memory_type: object) -> str:
    raw = str(memory_type or "session_summary").strip()
    aliases = {
        "feedback": "correction",
        "style_feedback": "correction",
        "trigger": "recurring_trigger",
        "safety": "safety_summary",
        "summary": "session_summary",
        "support": "support_strategy",
    }
    return aliases.get(raw, raw if raw in ALL_MEMORY_TYPES else "session_summary")


def _derive_title(memory_type: str, content: str) -> str:
    prefix = MEMORY_TYPE_LABELS.get(memory_type, "记忆")
    return f"{prefix}：{_clean_text(content, limit=36)}"


def _derive_tags(content: str, explicit_tags: object = None) -> list[str]:
    tags: list[str] = []
    if isinstance(explicit_tags, list):
        tags.extend(_clean_text(tag, limit=20) for tag in explicit_tags if _clean_text(tag))
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword in content for keyword in keywords):
            tags.append(tag)
    return sorted(set(tags))[:8]


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    cjk_chars = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return ascii_words | cjk_chars


def _term_similarity(query: str, document: str) -> float:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.0
    doc_terms = _tokenize(document)
    if not doc_terms:
        return 0.0
    return len(query_terms & doc_terms) / max(len(query_terms), 1)


def _content_similarity(left: str, right: str) -> float:
    left_text = _clean_text(left).lower()
    right_text = _clean_text(right).lower()
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _should_compare_memory_content(existing_content: object, candidate_content: object) -> bool:
    left = _clean_text(existing_content)
    right = _clean_text(candidate_content)
    if not left or not right:
        return False
    if left == right:
        return True

    shorter_length = min(len(left), len(right))
    longer_length = max(len(left), len(right))
    if shorter_length / longer_length < 0.45:
        return False
    if shorter_length < 12:
        return True
    return bool(_tokenize(left) & _tokenize(right))


def _freshness_warning(memory: UserMemory) -> str:
    updated_at = memory.updated_at or memory.created_at
    if not updated_at:
        return ""
    age_days = max((utcnow() - _aware(updated_at)).days, 0)
    if age_days <= 1:
        return ""
    return f"这条记忆已有 {age_days} 天，使用前应轻量验证。"


def _memory_document(memory: UserMemory) -> str:
    parts = [
        memory.title or "",
        memory.summary or "",
        memory.content or "",
        " ".join(memory.tags or []),
    ]
    structured = memory.structured_value or {}
    if isinstance(structured, dict):
        parts.extend(str(value) for value in structured.values() if isinstance(value, (str, int, float)))
    return " ".join(_clean_text(part) for part in parts if _clean_text(part))


def _snapshot(memory: UserMemory | None) -> dict[str, Any] | None:
    if memory is None:
        return None
    return {
        "memory_id": memory.id,
        "memory_type": memory.memory_type,
        "title": memory.title,
        "summary": memory.summary,
        "content": memory.content,
        "tags": list(memory.tags or []),
        "importance": memory.importance,
        "confidence": float(memory.confidence or 0),
        "visibility": memory.visibility,
        "status": memory.status,
        "source": memory.source,
        "version": memory.version,
        "review_state": memory.review_state,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def log_memory_operation(
    db: Session,
    *,
    user_id: str,
    memory_id: str | None,
    action: str,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
    reason: str | None = None,
    actor: str = "system",
) -> MemoryOperation:
    operation = MemoryOperation(
        user_id=user_id,
        memory_id=memory_id,
        action=action,
        before_value=before_value,
        after_value=after_value,
        reason=reason,
        actor=actor,
    )
    db.add(operation)
    db.flush()
    return operation


def remove_memory_vectors(memory_ids: list[str]) -> bool:
    ids = [str(memory_id) for memory_id in dict.fromkeys(memory_ids) if str(memory_id)]
    if not ids:
        return True
    try:
        return bool(milvus_store.delete_memory_vectors(ids))
    except Exception as exc:
        logger.warning("Milvus memory vector delete failed: %s", exc)
        return False


def _upsert_memory_vectors_with_retry(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return True
    memory_ids = [str(row.get("memory_id") or row.get("id") or "") for row in rows]
    memory_ids = [memory_id for memory_id in dict.fromkeys(memory_ids) if memory_id]
    last_error: Exception | None = None
    for _ in range(MEMORY_VECTOR_UPSERT_MAX_ATTEMPTS):
        try:
            if milvus_store.upsert_memory_vectors(rows):
                return True
        except Exception as exc:
            last_error = exc
    logger.warning(
        "Milvus memory vector upsert failed after %s attempts for memory_ids=%s%s",
        MEMORY_VECTOR_UPSERT_MAX_ATTEMPTS,
        memory_ids,
        f": {last_error}" if last_error is not None else "",
    )
    return False


def _base_memory_query(db: Session, user_id: str, memory_types: set[str] | None = None):
    now = utcnow()
    stmt = (
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_state != "do_not_use",
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
        )
        .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        .limit(200)
    )
    if memory_types is not None:
        if not memory_types:
            return db.scalars(select(UserMemory).where(false()))
        stmt = stmt.where(UserMemory.memory_type.in_(tuple(memory_types)))
    return db.scalars(stmt)


def _allowed_memory_types_for_mode(memory_mode: str, *, include_internal: bool = False) -> set[str]:
    if memory_mode == "off":
        return set()
    if memory_mode == "summary_only":
        types = {"session_summary"}
    else:
        types = set(VISIBLE_MEMORY_TYPES)
    if include_internal:
        types |= INTERNAL_MEMORY_TYPES
    return types


def build_memory_index(
    db: Session,
    user_id: str,
    *,
    memory_mode: str,
    limit: int = 20,
    include_internal: bool = False,
) -> list[dict[str, Any]]:
    allowed_types = INTERNAL_MEMORY_TYPES if include_internal else _allowed_memory_types_for_mode(memory_mode)
    if not allowed_types:
        return []

    items = []
    for memory in _base_memory_query(db, user_id, memory_types=allowed_types):
        if include_internal:
            if memory.visibility != "internal_safety":
                continue
        elif memory.visibility != "user_visible":
            continue
        description = memory.summary or memory.content
        items.append(
            {
                "memory_id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title or _derive_title(memory.memory_type, memory.content),
                "description": _clean_text(description, limit=140),
                "importance": memory.importance,
                "visibility": memory.visibility,
                "updated_at": memory.updated_at.isoformat(),
                "freshness_warning": _freshness_warning(memory),
            }
        )
        if len(items) >= limit:
            break
    return items


def _query_for_retrieval(
    *,
    query: str,
    recent_messages: list[dict[str, Any]] | None,
    last_summary: str | None,
    session_digest: dict[str, Any] | None,
    goal_state: dict[str, Any] | None,
    control_category: str | None,
) -> str:
    recent_text = " ".join(str(message.get("content", "")) for message in (recent_messages or [])[-4:])
    digest_parts: list[str] = []
    if isinstance(session_digest, dict):
        for key in ("key_themes", "emotional_arc", "unresolved_threads", "significant_changes", "summary_200chars"):
            value = session_digest.get(key)
            if isinstance(value, list):
                digest_parts.extend(str(item) for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                digest_parts.append(value.strip())
    digest_text = " ".join(digest_parts)
    goal_parts: list[str] = []
    if isinstance(goal_state, dict):
        for key in ("current_goal", "usage_goals", "goal_hints", "open_threads", "clarification_answer"):
            value = goal_state.get(key)
            if isinstance(value, list):
                goal_parts.extend(str(item) for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                goal_parts.append(value.strip())
    goal_text = " ".join(goal_parts)
    return _clean_text(
        f"{query} {last_summary or ''} {control_category or ''} {goal_text} {digest_text} {recent_text}",
        limit=1400,
    )


def _goal_state_has_context(goal_state: dict[str, Any] | None) -> bool:
    if not isinstance(goal_state, dict):
        return False
    for key in ("current_goal", "usage_goals", "goal_hints", "open_threads", "clarification_answer"):
        value = goal_state.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def _has_correction_signal(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in CORRECTION_SIGNAL_TERMS)


def _conflict_topic_terms(text: str) -> set[str]:
    lowered = text.lower()
    return {term for term in CONFLICT_TOPIC_TERMS if term.lower() in lowered}


def _conflict_arbitration_boost(memory_type: str, query_text: str) -> float:
    if not _has_correction_signal(query_text):
        return 0.0
    if memory_type == "correction":
        return 0.22
    if memory_type in CONFLICT_MEMORY_TYPES and _conflict_topic_terms(query_text):
        return -0.12
    return 0.0


def _type_boost(
    memory_type: str,
    query_text: str,
    control_category: str | None,
    goal_state: dict[str, Any] | None = None,
) -> float:
    text = query_text.lower()
    boost = 0.0
    if memory_type == "goal" and any(term in text for term in ("目标", "计划", "打算", "我想", "希望", "理清", "解决")):
        boost += 0.12
    if memory_type == "session_summary" and any(term in text for term in ("上次", "继续", "刚才", "最近")):
        boost += 0.08
    if memory_type == "session_summary" and any(term in text for term in ("职场", "工作", "压力", "主题", "方向", "讨论")):
        boost += 0.1
    if memory_type == "preference" and any(term in text for term in ("喜欢", "希望", "不要", "别", "方式")):
        boost += 0.08
    if memory_type == "correction" and any(
        term in text for term in ("不要", "别", "纠正", "先听", "听我说", "不是", "不喜欢")
    ):
        boost += 0.16
    if memory_type in {"recurring_trigger", "state"} and any(term in text for term in ("焦虑", "睡", "压力", "每次", "总是")):
        boost += 0.07
    if memory_type == "support_strategy" and any(term in text for term in ("安抚", "呼吸", "练习", "帮助", "有效")):
        boost += 0.07
    if memory_type == "relationship" and any(term in text for term in ("朋友", "家人", "同学", "伴侣", "关系")):
        boost += 0.07
    if control_category and memory_type in {"support_strategy", "recurring_trigger"}:
        boost += 0.03
    if _goal_state_has_context(goal_state) and any(term in text for term in ("继续", "这个", "刚才", "还是", "接着")):
        if memory_type == "goal":
            boost += 0.18
        elif memory_type in {"profile", "correction", "preference"}:
            boost += 0.12
        elif memory_type == "session_summary":
            boost -= 0.04
    boost += _conflict_arbitration_boost(memory_type, query_text)
    return boost


def _score_memory(
    memory: UserMemory,
    query_text: str,
    control_category: str | None,
    goal_state: dict[str, Any] | None = None,
) -> tuple[float, str]:
    document = _memory_document(memory)
    similarity = _term_similarity(query_text, document)
    importance_score = max(min(memory.importance, 5), 1) / 5
    updated_at = memory.updated_at or memory.created_at
    age_days = max((utcnow() - _aware(updated_at)).days, 0) if updated_at else 365
    freshness_score = max(0.0, 1.0 - min(age_days, 90) / 90)
    access_score = min(memory.access_count or 0, 10) / 10
    score = (
        0.46 * similarity
        + 0.28 * importance_score
        + 0.12 * freshness_score
        + 0.06 * access_score
        + _type_boost(memory.memory_type, query_text, control_category, goal_state)
    )
    if memory.review_state == "needs_review":
        score -= 0.08
    if similarity >= 0.18:
        reason = "与当前输入或近期上下文相似"
    elif memory.importance >= 4:
        reason = "高重要度记忆"
    elif memory.memory_type == "session_summary":
        reason = "近期会话摘要"
    else:
        reason = "长期记忆索引候选"
    return round(score, 4), reason


def _vector_retrieval_enabled() -> bool:
    explicit = os.getenv("MEMORY_VECTOR_RETRIEVAL_ENABLED")
    if explicit is not None:
        return explicit.lower() in {"1", "true", "yes", "on"}
    return os.getenv("MEMORY_EMBEDDINGS_ENABLED", "0").lower() in {"1", "true", "yes", "on"}


def _vector_score_memory(
    memory: UserMemory,
    *,
    vector_score: float,
    query_text: str,
    control_category: str | None,
    goal_state: dict[str, Any] | None = None,
) -> tuple[float, str]:
    importance_score = max(min(memory.importance, 5), 1) / 5
    updated_at = memory.updated_at or memory.created_at
    age_days = max((utcnow() - _aware(updated_at)).days, 0) if updated_at else 365
    freshness_score = max(0.0, 1.0 - min(age_days, 90) / 90)
    access_score = min(memory.access_count or 0, 10) / 10
    normalized_vector_score = max(0.0, min(float(vector_score or 0.0), 1.0))
    score = (
        0.62 * normalized_vector_score
        + 0.18 * importance_score
        + 0.10 * freshness_score
        + 0.04 * access_score
        + _type_boost(memory.memory_type, query_text, control_category, goal_state)
    )
    if memory.review_state == "needs_review":
        score -= 0.08
    return round(score, 4), "vector_semantic_match"


def _memory_visible_for_turn(memory: UserMemory, *, allowed_types: set[str], risk_level: str) -> bool:
    if memory.memory_type not in allowed_types:
        return False
    if risk_level in {"L2", "L3"}:
        return memory.visibility == "internal_safety" and memory.memory_type == "safety_summary"
    return memory.visibility == "user_visible"


def _memory_ids_from_vector_hits(
    *,
    user_id: str,
    query_vector: list[float] | None,
    allowed_types: set[str],
    risk_level: str,
    limit: int,
) -> dict[str, float]:
    if not query_vector or not _vector_retrieval_enabled() or not milvus_store.is_enabled:
        return {}
    memory_types = None if risk_level in {"L2", "L3"} else sorted(allowed_types)
    try:
        hits = milvus_store.search_user_memories(
            query_vector,
            user_id=user_id,
            memory_types=memory_types,
            risk_level=risk_level,
            limit=max(limit * 4, 20),
        )
    except Exception:
        return {}
    scores: dict[str, float] = {}
    for hit in hits:
        memory_id = str(hit.entity.get("memory_id") or hit.id or "")
        if not memory_id:
            continue
        scores[memory_id] = max(scores.get(memory_id, 0.0), float(hit.score or 0.0))
    return scores


def _fetch_memories_by_ids(db: Session, *, user_id: str, memory_ids: list[str]) -> list[UserMemory]:
    if not memory_ids:
        return []
    now = utcnow()
    return list(
        db.scalars(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.id.in_(memory_ids),
                UserMemory.status == "active",
                UserMemory.review_state != "do_not_use",
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
        )
    )


def retrieve_memories_for_turn(
    db: Session,
    *,
    user_id: str,
    query: str,
    recent_messages: list[dict[str, Any]] | None = None,
    last_summary: str | None = None,
    session_digest: dict[str, Any] | None = None,
    goal_state: dict[str, Any] | None = None,
    memory_mode: str,
    risk_level: str = "L0",
    control_category: str | None = None,
    limit: int = 5,
    record_access: bool = True,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    if memory_mode == "off":
        return []

    include_internal = risk_level in {"L2", "L3"}
    allowed_types = _allowed_memory_types_for_mode(memory_mode, include_internal=include_internal)
    if include_internal:
        allowed_types = {"safety_summary"}
    if not allowed_types:
        return []

    query_text = _query_for_retrieval(
        query=query,
        recent_messages=recent_messages,
        last_summary=last_summary,
        session_digest=session_digest,
        goal_state=goal_state,
        control_category=control_category,
    )

    vector_scores = _memory_ids_from_vector_hits(
        user_id=user_id,
        query_vector=query_vector,
        allowed_types=allowed_types,
        risk_level=risk_level,
        limit=limit,
    )
    candidate_memories: dict[str, UserMemory] = {}
    for memory in _base_memory_query(db, user_id, memory_types=allowed_types):
        if not _memory_visible_for_turn(memory, allowed_types=allowed_types, risk_level=risk_level):
            continue
        candidate_memories[memory.id] = memory
    for memory in _fetch_memories_by_ids(db, user_id=user_id, memory_ids=list(vector_scores.keys())):
        if _memory_visible_for_turn(memory, allowed_types=allowed_types, risk_level=risk_level):
            candidate_memories[memory.id] = memory

    candidates: list[tuple[float, str, UserMemory]] = []
    for memory in candidate_memories.values():
        score, reason = _score_memory(memory, query_text, control_category, goal_state)
        if memory.id in vector_scores:
            vector_score, vector_reason = _vector_score_memory(
                memory,
                vector_score=vector_scores[memory.id],
                query_text=query_text,
                control_category=control_category,
                goal_state=goal_state,
            )
            if vector_score >= score:
                score, reason = vector_score, vector_reason
        candidates.append((score, reason, memory))

    candidates.sort(
        key=lambda item: (
            item[0],
            item[2].importance,
            item[2].updated_at,
            -TYPE_PRIORITY.get(item[2].memory_type, 99),
        ),
        reverse=True,
    )
    selected = candidates[: max(limit, 0)]
    now = utcnow()
    results = []
    for score, reason, memory in selected:
        if record_access:
            memory.last_accessed_at = now
            memory.access_count = int(memory.access_count or 0) + 1
        results.append(
            {
                "id": memory.id,
                "memory_id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title or _derive_title(memory.memory_type, memory.content),
                "summary": memory.summary or _clean_text(memory.content, limit=140),
                "content": memory.content,
                "tags": list(memory.tags or []),
                "visibility": memory.visibility,
                "updated_at": memory.updated_at.isoformat(),
                "score": score,
                "why_selected": reason,
                "freshness_warning": _freshness_warning(memory),
                "source": memory.source,
            }
        )

    if selected and record_access:
        log_memory_operation(
            db,
            user_id=user_id,
            memory_id=None,
            action="retrieve",
            after_value={
                "memory_ids": [memory.id for _, _, memory in selected],
                "risk_level": risk_level,
                "control_category": control_category,
            },
            reason="turn_memory_retrieval",
        )
    return results


async def retrieve_memories_for_turn_async(
    db: Session,
    *,
    user_id: str,
    query: str,
    recent_messages: list[dict[str, Any]] | None = None,
    last_summary: str | None = None,
    session_digest: dict[str, Any] | None = None,
    goal_state: dict[str, Any] | None = None,
    memory_mode: str,
    risk_level: str = "L0",
    control_category: str | None = None,
    limit: int = 5,
    record_access: bool = True,
) -> list[dict[str, Any]]:
    query_vector = None
    if (
        memory_mode != "off"
        and _vector_retrieval_enabled()
        and milvus_store.is_available
        and embedding_client.is_configured
    ):
        query_text = _query_for_retrieval(
            query=query,
            recent_messages=recent_messages,
            last_summary=last_summary,
            session_digest=session_digest,
            goal_state=goal_state,
            control_category=control_category,
        )
        query_vector = await embedding_client.embed_query(query_text)
    return retrieve_memories_for_turn(
        db,
        user_id=user_id,
        query=query,
        recent_messages=recent_messages,
        last_summary=last_summary,
        session_digest=session_digest,
        goal_state=goal_state,
        memory_mode=memory_mode,
        risk_level=risk_level,
        control_category=control_category,
        limit=limit,
        record_access=record_access,
        query_vector=query_vector,
    )


def _unsafe_visible_memory_reason(content: str) -> str | None:
    lowered = content.lower()
    for term in UNSAFE_VISIBLE_TERMS:
        if term.lower() in lowered:
            return f"contains_sensitive_term:{term}"
    return None


def _candidate_structured_value(
    candidate: dict[str, Any],
    *,
    thread_id: str,
    risk_level: str,
) -> dict[str, Any]:
    structured = candidate.get("structured_value")
    if not isinstance(structured, dict):
        structured = {}
    structured.update(
        {
            "thread_id": thread_id,
            "risk_level": risk_level,
            "extracted_at": utcnow().isoformat(),
        }
    )
    return structured


def _find_similar_memory(
    db: Session,
    *,
    user_id: str,
    memory_type: str,
    visibility: str,
    content: str,
) -> UserMemory | None:
    now = utcnow()
    rows = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.memory_type == memory_type,
                UserMemory.visibility == visibility,
                UserMemory.review_state != "do_not_use",
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
            .order_by(desc(UserMemory.updated_at))
            .limit(50)
        )
    )
    exact = next((memory for memory in rows if _clean_text(memory.content) == _clean_text(content)), None)
    if exact is not None:
        return exact
    best: tuple[float, UserMemory] | None = None
    for memory in rows:
        if not _should_compare_memory_content(memory.content, content):
            continue
        similarity = _content_similarity(memory.content, content)
        if best is None or similarity > best[0]:
            best = (similarity, memory)
    if best is not None and best[0] >= 0.88:
        return best[1]
    return None


def _visibility_for_candidate(memory_type: str, candidate: dict[str, Any], risk_level: str) -> str:
    raw = str(candidate.get("visibility") or "").strip()
    if raw in {"internal", "internal_safety"}:
        return "internal_safety"
    if memory_type == "safety_summary" or risk_level in {"L2", "L3"}:
        return "internal_safety"
    return "user_visible"


def _allowed_write_types(memory_mode: str, risk_level: str) -> set[str]:
    if memory_mode == "off":
        return {"safety_summary"} if risk_level in {"L2", "L3"} else set()
    if memory_mode == "summary_only":
        return {"session_summary", "safety_summary"}
    return set(ALL_MEMORY_TYPES)


def _candidate_from_summary(default_summary: str, risk_level: str) -> dict[str, Any] | None:
    if not default_summary:
        return None
    return {
        "memory_type": "safety_summary" if risk_level in {"L2", "L3"} else "session_summary",
        "content": default_summary,
        "importance": 5 if risk_level in {"L2", "L3"} else 3,
    }


def _memory_conflicts_with_correction(memory: UserMemory, correction: UserMemory) -> bool:
    if correction.memory_type != "correction" or memory.memory_type not in CONFLICT_MEMORY_TYPES:
        return False
    correction_text = _clean_text(correction.content)
    if not _has_correction_signal(correction_text):
        return False
    correction_terms = _conflict_topic_terms(correction_text)
    if not correction_terms:
        return False
    memory_terms = _conflict_topic_terms(_memory_document(memory))
    return bool(correction_terms & memory_terms)


def _mark_conflicting_memories_for_review(db: Session, *, user_id: str, correction: UserMemory) -> list[UserMemory]:
    if correction.visibility != "user_visible" or correction.memory_type != "correction":
        return []
    now = utcnow()
    rows = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.id != correction.id,
                UserMemory.status == "active",
                UserMemory.visibility == "user_visible",
                UserMemory.memory_type.in_(tuple(CONFLICT_MEMORY_TYPES)),
                UserMemory.review_state != "do_not_use",
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
            .order_by(desc(UserMemory.updated_at))
            .limit(50)
        )
    )
    marked: list[UserMemory] = []
    correction_terms = sorted(_conflict_topic_terms(correction.content))
    for memory in rows:
        if not _memory_conflicts_with_correction(memory, correction):
            continue
        structured = dict(memory.structured_value or {})
        conflict = structured.get("memory_conflict")
        if isinstance(conflict, dict) and conflict.get("superseded_by") == correction.id:
            continue
        before = _snapshot(memory)
        structured["memory_conflict"] = {
            "superseded_by": correction.id,
            "superseding_type": correction.memory_type,
            "reason": "correction_conflict",
            "terms": correction_terms[:6],
            "detected_at": now.isoformat(),
        }
        memory.structured_value = structured
        memory.review_state = "needs_review"
        memory.updated_at = now
        memory.version = int(memory.version or 1) + 1
        db.flush()
        log_memory_operation(
            db,
            user_id=user_id,
            memory_id=memory.id,
            action="feedback",
            before_value=before,
            after_value=_snapshot(memory),
            reason=f"correction_conflict:{correction.id}",
        )
        marked.append(memory)
    return marked


def upsert_memory_candidates(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    assistant_message_id: str,
    assistant_result: dict[str, Any],
    memory_mode_override: str | None = None,
) -> tuple[list[UserMemory], list[dict[str, Any]]]:
    if not bool(assistant_result.get("should_write_memory")):
        return [], [{"status": "skipped", "reason": "assistant_result_disabled"}]

    memory_mode = memory_mode_override or (
        getattr(user.settings, "memory_mode", "summary_only") if user.settings else "summary_only"
    )
    risk_level = str(assistant_result.get("risk_level", "L0"))
    memory_policy = str(assistant_result.get("memory_policy", "write_safe_summary"))
    if memory_policy == "skip_sensitive" and risk_level not in {"L2", "L3"}:
        return [], [{"status": "skipped", "reason": "memory_policy_skip_sensitive"}]

    raw_candidates = [
        candidate
        for candidate in assistant_result.get("memory_candidates", [])
        if isinstance(candidate, dict) and _clean_text(candidate.get("content"))
    ]
    if not raw_candidates:
        fallback = _candidate_from_summary(_clean_text(assistant_result.get("session_summary")), risk_level)
        raw_candidates = [fallback] if fallback else []
    if not raw_candidates:
        return [], [{"status": "skipped", "reason": "no_candidates"}]

    allowed_types = _allowed_write_types(memory_mode, risk_level)
    written: list[UserMemory] = []
    decisions: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        memory_type = _normalize_memory_type(candidate.get("memory_type"))
        content = _clean_text(candidate.get("content"), limit=1200)
        if not content:
            continue
        if memory_type not in allowed_types:
            decisions.append({"status": "blocked", "memory_type": memory_type, "reason": "memory_mode"})
            continue
        if memory_mode == "summary_only" and risk_level in {"L0", "L1"} and memory_type != "session_summary":
            decisions.append({"status": "blocked", "memory_type": memory_type, "reason": "summary_only"})
            continue

        visibility = _visibility_for_candidate(memory_type, candidate, risk_level)
        if visibility == "user_visible":
            unsafe_reason = _unsafe_visible_memory_reason(content)
            if unsafe_reason:
                decisions.append({"status": "blocked", "memory_type": memory_type, "reason": unsafe_reason})
                continue

        try:
            importance = int(candidate.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        importance = max(1, min(5, importance))
        title = _clean_text(candidate.get("title"), limit=120) or _derive_title(memory_type, content)
        summary = _clean_text(candidate.get("summary"), limit=260) or _clean_text(content, limit=180)
        tags = _derive_tags(content, candidate.get("tags"))
        structured_value = _candidate_structured_value(candidate, thread_id=thread.id, risk_level=risk_level)

        existing = _find_similar_memory(
            db,
            user_id=user.id,
            memory_type=memory_type,
            visibility=visibility,
            content=content,
        )
        if existing is not None:
            before = _snapshot(existing)
            existing.title = title or existing.title
            existing.summary = summary
            existing.content = content if len(content) > len(existing.content or "") else existing.content
            existing.tags = sorted(set(list(existing.tags or []) + tags))[:8]
            merged_structured = dict(existing.structured_value or {})
            merged_structured.update(structured_value)
            existing.structured_value = merged_structured
            existing.importance = max(existing.importance or 1, importance)
            existing.confidence = max(float(existing.confidence or 0), 0.7)
            existing.source_thread_id = thread.id
            existing.source_message_id = assistant_message_id
            existing.updated_at = utcnow()
            existing.version = int(existing.version or 1) + 1
            db.flush()
            log_memory_operation(
                db,
                user_id=user.id,
                memory_id=existing.id,
                action="update",
                before_value=before,
                after_value=_snapshot(existing),
                reason="similar_candidate_merge",
            )
            written.append(existing)
            decisions.append({"status": "updated", "memory_id": existing.id, "memory_type": memory_type})
            _mark_conflicting_memories_for_review(db, user_id=user.id, correction=existing)
            continue

        memory = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            title=title,
            summary=summary,
            content=content,
            structured_value=structured_value,
            tags=tags,
            importance=importance,
            confidence=0.7,
            source_thread_id=thread.id,
            source_message_id=assistant_message_id,
            visibility=visibility,
            status="active",
            source="chat",
            review_state="normal",
        )
        db.add(memory)
        db.flush()
        log_memory_operation(
            db,
            user_id=user.id,
            memory_id=memory.id,
            action="create",
            after_value=_snapshot(memory),
            reason="turn_candidate",
        )
        written.append(memory)
        decisions.append({"status": "created", "memory_id": memory.id, "memory_type": memory_type})
        _mark_conflicting_memories_for_review(db, user_id=user.id, correction=memory)
    return written, decisions


async def index_memory_embeddings(db: Session, memories: list[UserMemory]) -> None:
    if os.getenv("MEMORY_EMBEDDINGS_ENABLED", "0").lower() not in {"1", "true", "yes", "on"}:
        return
    active_memories = [memory for memory in memories if memory.status == "active" and memory.content]
    if not active_memories or not embedding_client.is_configured:
        return
    texts = [memory.content for memory in active_memories]
    vectors = await embedding_client.embed_texts(texts)
    if not vectors or len(vectors) != len(active_memories):
        return
    memory_ids = [memory.id for memory in active_memories]
    existing_embeddings: dict[str, MemoryEmbedding] = {}
    for existing in db.scalars(
        select(MemoryEmbedding)
        .where(
            MemoryEmbedding.memory_id.in_(memory_ids),
            MemoryEmbedding.embedding_key == embedding_client.embedding_key,
        )
        .order_by(desc(MemoryEmbedding.updated_at), desc(MemoryEmbedding.created_at))
    ):
        existing_embeddings.setdefault(existing.memory_id, existing)
    milvus_rows: list[dict[str, Any]] = []
    for memory, vector in zip(active_memories, vectors):
        content_hash = sha256(memory.content.encode("utf-8")).hexdigest()
        existing = existing_embeddings.get(memory.id)
        if existing is None:
            db.add(
                MemoryEmbedding(
                    memory_id=memory.id,
                    user_id=memory.user_id,
                    embedding=vector,
                    embedding_model=embedding_client.model,
                    embedding_key=embedding_client.embedding_key,
                    content_hash=content_hash,
                )
            )
        else:
            existing.embedding = vector
            existing.embedding_model = embedding_client.model
            existing.content_hash = content_hash
            existing.updated_at = utcnow()
        milvus_rows.append(
            {
                "id": memory.id,
                "memory_id": memory.id,
                "user_id": memory.user_id,
                "memory_type": memory.memory_type,
                "visibility": memory.visibility,
                "status": memory.status,
                "review_state": memory.review_state,
                "title": memory.title or "",
                "source": memory.source,
                "embedding_key": embedding_client.embedding_key,
                "updated_at": memory.updated_at.isoformat(),
                "content": memory.content,
                "vector": vector,
            }
        )
    if milvus_rows:
        _upsert_memory_vectors_with_retry(milvus_rows)
    db.flush()


def _active_visible_memories(db: Session, user_id: str) -> list[UserMemory]:
    return list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.visibility == "user_visible",
            )
            .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        )
    )


def _consolidate_duplicate_memories(db: Session, user_id: str) -> int:
    memories = _active_visible_memories(db, user_id)
    by_type: dict[str, list[UserMemory]] = defaultdict(list)
    for memory in memories:
        by_type[memory.memory_type].append(memory)

    touched = 0
    deleted_memory_ids: list[str] = []
    for memory_type, group in by_type.items():
        kept: list[UserMemory] = []
        for memory in group:
            match = next(
                (
                    existing
                    for existing in kept
                    if _content_similarity(existing.content, memory.content) >= 0.9
                    or (existing.title and memory.title and existing.title == memory.title)
                ),
                None,
            )
            if match is None:
                kept.append(memory)
                continue
            before_match = _snapshot(match)
            before_memory = _snapshot(memory)
            match.importance = max(match.importance or 1, memory.importance or 1)
            match.tags = sorted(set(list(match.tags or []) + list(memory.tags or [])))[:8]
            match.summary = match.summary or memory.summary
            match.version = int(match.version or 1) + 1
            match.updated_at = utcnow()
            memory.status = "deleted"
            memory.supersedes_id = match.id
            memory.updated_at = utcnow()
            deleted_memory_ids.append(memory.id)
            touched += 2
            db.flush()
            log_memory_operation(
                db,
                user_id=user_id,
                memory_id=match.id,
                action="consolidate",
                before_value=before_match,
                after_value=_snapshot(match),
                reason=f"merged_duplicate:{memory_type}",
            )
            log_memory_operation(
                db,
                user_id=user_id,
                memory_id=memory.id,
                action="delete",
                before_value=before_memory,
                after_value=_snapshot(memory),
                reason=f"superseded_by:{match.id}",
            )
    remove_memory_vectors(deleted_memory_ids)
    return touched


def _upsert_mood_state_memory(db: Session, user_id: str) -> int:
    since = utcnow() - timedelta(days=14)
    logs = list(
        db.scalars(
            select(MoodLog)
            .where(MoodLog.user_id == user_id, MoodLog.created_at >= since)
            .order_by(MoodLog.created_at.desc())
        )
    )
    if len(logs) < 3:
        return 0
    avg_mood = round(sum(log.mood_score for log in logs) / len(logs), 2)
    tag_counter: Counter[str] = Counter()
    for log in logs:
        for tag in log.mood_tags or []:
            if _clean_text(tag):
                tag_counter[_clean_text(tag)] += 1
    top_tags = [tag for tag, _ in tag_counter.most_common(5)]
    content = f"近 14 天记录 {len(logs)} 次情绪，平均情绪分 {avg_mood}/5。"
    if top_tags:
        content += f" 高频情绪标签：{'、'.join(top_tags[:5])}。"
    candidate = {
        "memory_type": "state",
        "title": "近 14 天情绪趋势",
        "summary": content,
        "content": content,
        "importance": 4,
        "tags": top_tags,
        "structured_value": {
            "avg_mood_score": avg_mood,
            "log_count": len(logs),
            "top_tags": top_tags,
            "time_range_days": 14,
        },
    }
    existing = _find_similar_memory(
        db,
        user_id=user_id,
        memory_type="state",
        visibility="user_visible",
        content=content,
    )
    if existing is not None:
        before = _snapshot(existing)
        existing.title = "近 14 天情绪趋势"
        existing.summary = content
        existing.content = content
        existing.tags = top_tags
        existing.structured_value = candidate["structured_value"]
        existing.updated_at = utcnow()
        existing.version = int(existing.version or 1) + 1
        db.flush()
        log_memory_operation(
            db,
            user_id=user_id,
            memory_id=existing.id,
            action="consolidate",
            before_value=before,
            after_value=_snapshot(existing),
            reason="mood_state_refresh",
        )
        return 1

    memory = UserMemory(
        user_id=user_id,
        memory_type="state",
        title="近 14 天情绪趋势",
        summary=content,
        content=content,
        structured_value=candidate["structured_value"],
        tags=top_tags,
        importance=4,
        confidence=0.8,
        visibility="user_visible",
        status="active",
        source="mood_consolidation",
    )
    db.add(memory)
    db.flush()
    log_memory_operation(
        db,
        user_id=user_id,
        memory_id=memory.id,
        action="create",
        after_value=_snapshot(memory),
        reason="mood_state_consolidation",
    )
    return 1


def _expire_old_memories(db: Session, user_id: str) -> int:
    now = utcnow()
    expired = list(
        db.scalars(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.expires_at.is_not(None),
                UserMemory.expires_at <= now,
            )
        )
    )
    for memory in expired:
        before = _snapshot(memory)
        memory.status = "expired"
        memory.updated_at = now
        log_memory_operation(
            db,
            user_id=user_id,
            memory_id=memory.id,
            action="expire",
            before_value=before,
            after_value=_snapshot(memory),
            reason="expires_at_elapsed",
        )
    remove_memory_vectors([memory.id for memory in expired])
    return len(expired)


def consolidate_user_memories(
    db: Session,
    *,
    user_id: str,
    trigger: str = "manual",
    force: bool = False,
) -> dict[str, Any]:
    running = db.scalar(
        select(MemoryConsolidationRun)
        .where(
            MemoryConsolidationRun.user_id == user_id,
            MemoryConsolidationRun.status == "running",
            MemoryConsolidationRun.started_at >= utcnow() - timedelta(hours=1),
        )
        .order_by(desc(MemoryConsolidationRun.started_at))
    )
    if running is not None and not force:
        return {
            "run_id": running.id,
            "status": "running",
            "sessions_reviewed": running.sessions_reviewed,
            "memories_touched": running.memories_touched,
        }

    session_count = db.scalar(
        select(func.count(ConversationThread.id)).where(ConversationThread.user_id == user_id)
    )
    run = MemoryConsolidationRun(
        user_id=user_id,
        status="running",
        trigger=trigger,
        sessions_reviewed=int(session_count or 0),
    )
    db.add(run)
    db.flush()
    try:
        touched = 0
        touched += _expire_old_memories(db, user_id)
        touched += _consolidate_duplicate_memories(db, user_id)
        touched += _upsert_mood_state_memory(db, user_id)
        run.status = "completed"
        run.memories_touched = touched
        run.completed_at = utcnow()
        log_memory_operation(
            db,
            user_id=user_id,
            memory_id=None,
            action="consolidate",
            after_value={"run_id": run.id, "memories_touched": touched},
            reason=f"{trigger}_consolidation",
        )
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = utcnow()
        raise
    finally:
        db.flush()
    return {
        "run_id": run.id,
        "status": run.status,
        "sessions_reviewed": run.sessions_reviewed,
        "memories_touched": run.memories_touched,
        "error_message": run.error_message,
    }


def maybe_auto_consolidate_user_memories(db: Session, *, user_id: str) -> dict[str, Any] | None:
    last_completed = db.scalar(
        select(MemoryConsolidationRun)
        .where(
            MemoryConsolidationRun.user_id == user_id,
            MemoryConsolidationRun.status == "completed",
        )
        .order_by(desc(MemoryConsolidationRun.completed_at))
    )
    since = _aware(last_completed.completed_at) if last_completed and last_completed.completed_at else utcnow() - timedelta(days=365)
    if last_completed and last_completed.completed_at and utcnow() - _aware(last_completed.completed_at) < timedelta(hours=24):
        return None
    sessions_since = db.scalar(
        select(func.count(ConversationThread.id)).where(
            ConversationThread.user_id == user_id,
            ConversationThread.updated_at >= since,
        )
    )
    if int(sessions_since or 0) < 5:
        return None
    return consolidate_user_memories(db, user_id=user_id, trigger="auto", force=False)


def record_memory_feedback(
    db: Session,
    *,
    user_id: str,
    memory_id: str,
    feedback: str,
    note: str | None = None,
) -> UserMemory | None:
    memory = db.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.visibility == "user_visible",
        )
    )
    if memory is None:
        return None
    before = _snapshot(memory)
    normalized = feedback.strip().lower()
    if normalized == "accurate":
        memory.review_state = "confirmed"
        memory.confidence = min(float(memory.confidence or 0.5) + 0.1, 1.0)
    elif normalized == "inaccurate":
        memory.review_state = "needs_review"
        memory.confidence = max(float(memory.confidence or 0.5) - 0.2, 0.0)
    elif normalized in {"dont_use", "do_not_use"}:
        memory.review_state = "do_not_use"
        memory.status = "deleted"
    else:
        memory.review_state = "needs_review"
    memory.updated_at = utcnow()
    structured = dict(memory.structured_value or {})
    structured["latest_feedback"] = {"value": normalized, "note": note, "created_at": utcnow().isoformat()}
    memory.structured_value = structured
    db.flush()
    log_memory_operation(
        db,
        user_id=user_id,
        memory_id=memory.id,
        action="feedback",
        before_value=before,
        after_value=_snapshot(memory),
        reason=note or normalized,
        actor="user",
    )
    if memory.status == "deleted":
        remove_memory_vectors([memory.id])
    return memory


def count_memory_operations(db: Session, *, user_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(MemoryOperation.id)).where(MemoryOperation.user_id == user_id)
        )
        or 0
    )


def list_memory_operations(db: Session, *, user_id: str, limit: int = 50, offset: int = 0) -> list[MemoryOperation]:
    return list(
        db.scalars(
            select(MemoryOperation)
            .where(MemoryOperation.user_id == user_id)
            .order_by(desc(MemoryOperation.created_at))
            .limit(max(1, min(limit, 200)))
            .offset(max(offset, 0))
        )
    )
