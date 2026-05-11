from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.graphs.state import AgentState
from app.services.embedding_service import embedding_client
from app.services.milvus_service import milvus_store

if TYPE_CHECKING:
    from app.db.models import CounselingExampleChunk, CounselingCorpusSource


COUNSELING_CORPUS_SOURCES: dict[str, dict[str, Any]] = {
    "soulchat_corpus": {
        "source_key": "soulchat_corpus",
        "name": "SoulChatCorpus",
        "base_url": "https://github.com/scutcyr/SoulChat",
        "terms_url": "https://github.com/scutcyr/SoulChat/blob/main/LICENSE",
        "license": "apache-2.0",
        "language": "zh-CN",
        "is_commercial_allowed": True,
    },
    "smilechat": {
        "source_key": "smilechat",
        "name": "SMILECHAT",
        "base_url": "https://github.com/qiuhuachuan/smile",
        "terms_url": "https://github.com/qiuhuachuan/smile/blob/main/LICENSE",
        "license": "CC0-1.0",
        "language": "zh-CN",
        "is_commercial_allowed": True,
    },
    "cpsycound": {
        "source_key": "cpsycound",
        "name": "CPsyCounD",
        "base_url": "https://huggingface.co/datasets/CAS-SIAT-XinHai/CPsyCoun",
        "terms_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "license": "cc-by-sa-4.0",
        "language": "zh-CN",
        "is_commercial_allowed": True,
    },
    "psydt_corpus": {
        "source_key": "psydt_corpus",
        "name": "PsyDTCorpus",
        "base_url": "https://github.com/scutcyr/SoulChat2.0",
        "terms_url": "https://github.com/scutcyr/SoulChat2.0",
        "license": "research-use-check-source",
        "language": "zh-CN",
        "is_commercial_allowed": False,
    },
}


@dataclass(frozen=True)
class CounselingExampleHit:
    content: str
    source_key: str
    source_name: str
    mode: str | None
    source_url: str | None
    license: str | None
    score: float
    chunk_id: str | None = None
    scenario_tags: list[str] | None = None
    intervention_tags: list[str] | None = None
    style_tags: list[str] | None = None
    contraindications: list[str] | None = None
    quality_score: float | None = None
    safety_score: float | None = None
    review_status: str | None = None
    language: str | None = None
    age_group: str | None = None
    risk_allowed: str | None = None


def counseling_chunk_to_vector_row(
    chunk: CounselingExampleChunk,
    source: CounselingCorpusSource,
    vector: list[float],
) -> dict[str, object]:
    meta = dict(getattr(chunk, "meta", None) or {})
    tags = list(getattr(chunk, "tags", None) or [])
    return {
        "id": chunk.id,
        "chunk_id": chunk.id,
        "source_id": source.id,
        "source_key": source.source_key,
        "source_name": source.name,
        "external_id": chunk.external_id,
        "mode": chunk.mode,
        "topic": chunk.topic or "",
        "source_url": chunk.source_url or source.base_url,
        "license": chunk.license or source.license,
        "status": chunk.status,
        "embedding_key": embedding_client.embedding_key,
        "content": chunk.content,
        "language": meta.get("language") or getattr(source, "language", None) or "zh-CN",
        "age_group": meta.get("age_group") or "general",
        "review_status": meta.get("review_status") or "approved",
        "risk_allowed": meta.get("risk_allowed") or "non_crisis",
        "scenario_tags": ",".join(_as_text_list(meta.get("scenario_tags") or tags)),
        "intervention_tags": ",".join(_as_text_list(meta.get("intervention_tags"))),
        "style_tags": ",".join(_as_text_list(meta.get("style_tags") or ["supportive"])),
        "contraindications": ",".join(_as_text_list(meta.get("contraindications"))),
        "quality_score": str(meta.get("quality_score", "")),
        "safety_score": str(meta.get("safety_score", "")),
        "vector": vector,
    }


async def retrieve_counseling_examples(
    state: AgentState,
    *,
    mode: str,
    limit: int = 3,
) -> list[CounselingExampleHit]:
    if not settings.counseling_rag_enabled:
        return []
    allowed, _reason = counseling_rag_allowed(state)
    if not allowed:
        return []
    if state.get("risk_level") in {"L2", "L3"}:
        return []
    if not milvus_store.is_available:
        return []

    query = str(state.get("normalized_text") or "").strip()
    if not query:
        return []

    vector = await embedding_client.embed_query(query)
    if vector is None:
        return []

    hits: list[Any] = []
    seen_ids: set[str] = set()
    search_modes = _search_modes_for(mode)
    safe_limit = min(max(limit, 0), 3)
    if safe_limit <= 0:
        return []
    per_query_limit = max(safe_limit * 3, 9)
    for search_mode in search_modes:
        for hit in milvus_store.search_counseling_examples(vector, mode=search_mode, limit=per_query_limit):
            if hit.id in seen_ids:
                continue
            seen_ids.add(hit.id)
            content = str(hit.entity.get("content") or "").strip()
            if not content or not counseling_example_is_safe(hit.entity):
                continue
            hits.append(hit)
            if len(hits) >= safe_limit:
                break
        if len(hits) >= safe_limit:
            break

    examples: list[CounselingExampleHit] = []
    for hit in hits[:safe_limit]:
        content = str(hit.entity.get("content") or "").strip()
        if not content or not counseling_example_is_safe(hit.entity):
            continue
        examples.append(
            CounselingExampleHit(
                content=content,
                source_key=str(hit.entity.get("source_key") or ""),
                source_name=str(hit.entity.get("source_name") or "unknown"),
                mode=str(hit.entity.get("mode") or "") or None,
                source_url=str(hit.entity.get("source_url") or "") or None,
                license=str(hit.entity.get("license") or "") or None,
                score=hit.score,
                chunk_id=str(hit.entity.get("chunk_id") or hit.id or "") or None,
                scenario_tags=_split_tags(hit.entity.get("scenario_tags")),
                intervention_tags=_split_tags(hit.entity.get("intervention_tags")),
                style_tags=_split_tags(hit.entity.get("style_tags")),
                contraindications=_split_tags(hit.entity.get("contraindications")),
                quality_score=_to_float(hit.entity.get("quality_score")),
                safety_score=_to_float(hit.entity.get("safety_score")),
                review_status=str(hit.entity.get("review_status") or hit.entity.get("status") or "approved"),
                language=str(hit.entity.get("language") or "zh-CN"),
                age_group=str(hit.entity.get("age_group") or "general"),
                risk_allowed=str(hit.entity.get("risk_allowed") or "non_crisis"),
            )
        )
    return examples


def _search_modes_for(mode: str) -> list[str | None]:
    normalized = (mode or "").strip().lower()
    if normalized == "companion":
        return ["vent", "soothe", "counseling", None]
    if normalized == "vent":
        return ["vent", "soothe", None]
    if normalized == "soothe":
        return ["soothe", "vent", None]
    if normalized == "counseling":
        return ["counseling", "vent", None]
    return [normalized or None, None]


RAG_ALLOWED_PRIORITIES = {"P2_support", "P3_bridge_boundary"}
RAG_BLOCKED_CATEGORIES = {
    "abusive_to_assistant",
    "sexual_boundary",
    "harm_to_other_risk",
    "victimization_risk",
    "clinical_red_flag",
    "dependency_risk",
    "diagnosis_or_medical_request",
    "prompt_attack",
    "dangerous_request",
}
RAG_FORBIDDEN_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"自杀|自残|割腕|上吊|跳楼|结束生命|kill myself|end my life",
        r"杀了|弄死|捅|砍|报复|炸|kill (him|her|them)",
        r"剂量|毫克|mg\b|处方|停药|吃药",
        r"确诊|诊断为|你这是.{0,8}(抑郁症|焦虑症|双相|精神分裂)",
        r"一定能好|保证.{0,8}(康复|治好)|包治",
        r"只有我.{0,8}(懂你|陪你)|你离不开我|我永远陪你",
        r"做爱|约炮|裸照|强奸",
        r"热线|拨打\s*\d{3,}|电话\s*\d{3,}",
    ]
]
KNOWN_DISALLOWED_SOURCES = {
    key for key, source in COUNSELING_CORPUS_SOURCES.items() if not source.get("is_commercial_allowed", False)
}


def counseling_rag_allowed(state: AgentState) -> tuple[bool, str]:
    if state.get("risk_level") in {"L2", "L3"}:
        return False, "risk_level_blocks_rag"
    route_priority = str(state.get("route_priority") or "P2_support")
    if route_priority not in RAG_ALLOWED_PRIORITIES:
        return False, "route_priority_blocks_rag"
    control_category = str(state.get("control_category") or "")
    if control_category in RAG_BLOCKED_CATEGORIES:
        return False, "control_category_blocks_rag"
    rag_policy = state.get("rag_policy") or {}
    if rag_policy.get("enabled") is False:
        return False, str(rag_policy.get("skip_reason") or "rag_policy_disabled")
    return True, ""


def counseling_example_is_safe(entity: dict[str, Any]) -> bool:
    source_key = str(entity.get("source_key") or "")
    if source_key in KNOWN_DISALLOWED_SOURCES:
        return False

    status = str(entity.get("status") or "published").lower()
    review_status = str(entity.get("review_status") or "approved").lower()
    risk_allowed = str(entity.get("risk_allowed") or "non_crisis").lower()
    language = str(entity.get("language") or "zh-CN")
    contraindications = set(_split_tags(entity.get("contraindications")))

    if status != "published":
        return False
    if review_status not in {"approved", "published"}:
        return False
    if risk_allowed != "non_crisis":
        return False
    if language and language not in {"zh-CN", "zh", "general"}:
        return False
    if contraindications.intersection(
        {"crisis", "self_harm", "harm_to_other", "psychosis", "medical_request", "sexual_boundary"}
    ):
        return False

    content = str(entity.get("content") or "")
    return not any(pattern.search(content) for pattern in RAG_FORBIDDEN_PATTERNS)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _split_tags(value: Any) -> list[str]:
    return _as_text_list(value)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
