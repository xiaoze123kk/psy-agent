from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.graphs.state import AgentState
from app.services.embedding_service import embedding_client
from app.services.counseling_reranker import RerankCandidate, model_reranker
from app.services.milvus_service import milvus_store

if TYPE_CHECKING:
    from app.db.models import CounselingExampleChunk, CounselingCorpusSource


logger = logging.getLogger(__name__)

CHUNK_TYPES = {"turn_pair", "process_segment", "session_sketch"}
CONTINUATION_PATTERNS = ("继续", "还是", "刚才", "前面", "上次", "那个问题", "接着")


RERANK_RETRIEVAL_KEY = "_retrieval_key"


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
    chunk_type: str = "turn_pair"
    original_external_id: str | None = None
    phase: str | None = None
    display_text: str | None = None
    process_quality_score: float | None = None
    rerank_score: float | None = None
    rerank_reasons: list[str] | None = None


@dataclass(frozen=True)
class CounselingRetrievalResult:
    examples: list[CounselingExampleHit]
    trace: dict[str, object]


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _timeout_ms(timeout_seconds: float) -> int:
    return max(1, int(max(timeout_seconds, 0.001) * 1000))


def _retrieval_result(
    *,
    examples: list[CounselingExampleHit] | None = None,
    trace: dict[str, object],
    started_at: float,
) -> CounselingRetrievalResult:
    trace.setdefault("hit_count", len(examples or []))
    trace["total_duration_ms"] = _elapsed_ms(started_at)
    return CounselingRetrievalResult(examples=examples or [], trace=trace)


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
        "chunk_type": str(meta.get("chunk_type") or "turn_pair"),
        "original_external_id": str(meta.get("original_external_id") or chunk.external_id),
        "phase": str(meta.get("phase") or ""),
        "display_text": str(meta.get("display_text") or ""),
        "process_quality_score": str(meta.get("process_quality_score", "")),
        "vector": vector,
    }


async def retrieve_counseling_examples(
    state: AgentState,
    *,
    mode: str,
    limit: int = 3,
) -> list[CounselingExampleHit]:
    result = await retrieve_counseling_examples_with_trace(state, mode=mode, limit=limit)
    return result.examples


async def retrieve_counseling_examples_with_trace(
    state: AgentState,
    *,
    mode: str,
    limit: int = 3,
    timeout_seconds: float | None = None,
) -> CounselingRetrievalResult:
    started_at = perf_counter()
    timeout_budget = max(float(timeout_seconds or settings.rag_retrieval_timeout_seconds), 0.001)
    deadline = started_at + timeout_budget
    trace: dict[str, object] = {
        "status": "skipped",
        "mode": mode,
        "timeout_ms": _timeout_ms(timeout_budget),
        "embedding_duration_ms": 0,
        "milvus_duration_ms": 0,
    }

    def remaining_seconds() -> float:
        return max(deadline - perf_counter(), 0.001)

    if not settings.counseling_rag_enabled:
        trace["skipped_reason"] = "rag_disabled"
        return _retrieval_result(trace=trace, started_at=started_at)
    allowed, _reason = counseling_rag_allowed(state)
    if not allowed:
        trace["skipped_reason"] = _reason or "rag_policy_disabled"
        return _retrieval_result(trace=trace, started_at=started_at)
    if state.get("risk_level") in {"L2", "L3"}:
        trace["skipped_reason"] = "risk_level_blocks_rag"
        return _retrieval_result(trace=trace, started_at=started_at)
    if not milvus_store.is_available:
        trace["skipped_reason"] = "milvus_unavailable"
        return _retrieval_result(trace=trace, started_at=started_at)

    query = str(state.get("normalized_text") or "").strip()
    if not query:
        trace["skipped_reason"] = "empty_query"
        return _retrieval_result(trace=trace, started_at=started_at)

    embedding_started_at = perf_counter()
    try:
        vector = await asyncio.wait_for(embedding_client.embed_query(query), timeout=remaining_seconds())
    except asyncio.TimeoutError:
        trace["status"] = "timeout"
        trace["phase"] = "embedding"
        trace["skipped_reason"] = "rag_timeout"
        trace["embedding_duration_ms"] = _elapsed_ms(embedding_started_at)
        logger.warning("Counseling RAG embedding timed out after %.1fs.", timeout_budget)
        return _retrieval_result(trace=trace, started_at=started_at)
    trace["embedding_duration_ms"] = _elapsed_ms(embedding_started_at)
    if vector is None:
        trace["skipped_reason"] = "embedding_unavailable"
        return _retrieval_result(trace=trace, started_at=started_at)

    hits: list[Any] = []
    seen_ids: set[str] = set()
    search_modes = _search_modes_for(mode)
    trace["search_modes"] = [search_mode or "any" for search_mode in search_modes]
    safe_limit = min(max(limit, 0), 3)
    if safe_limit <= 0:
        trace["skipped_reason"] = "invalid_limit"
        return _retrieval_result(trace=trace, started_at=started_at)
    configured_recall_top_n = max(int(settings.counseling_recall_top_n), 0)
    per_query_limit = max(configured_recall_top_n, safe_limit * 6, 18)
    trace["recall_top_n"] = per_query_limit
    for search_mode in search_modes:
        search_started_at = perf_counter()
        try:
            search_hits = await asyncio.wait_for(
                asyncio.to_thread(
                    milvus_store.search_counseling_examples,
                    vector,
                    mode=search_mode,
                    limit=per_query_limit,
                ),
                timeout=remaining_seconds(),
            )
        except asyncio.TimeoutError:
            trace["status"] = "timeout"
            trace["phase"] = "milvus_search"
            trace["skipped_reason"] = "rag_timeout"
            trace["milvus_duration_ms"] = int(trace.get("milvus_duration_ms", 0)) + _elapsed_ms(search_started_at)
            logger.warning("Counseling RAG Milvus search timed out after %.1fs.", timeout_budget)
            return _retrieval_result(trace=trace, started_at=started_at)
        trace["milvus_duration_ms"] = int(trace.get("milvus_duration_ms", 0)) + _elapsed_ms(search_started_at)

        for hit in search_hits:
            if hit.id in seen_ids:
                continue
            seen_ids.add(hit.id)
            content = str(hit.entity.get("content") or "").strip()
            if not content or not counseling_example_is_safe(hit.entity):
                continue
            hits.append(hit)
            if len(hits) >= per_query_limit:
                break
        if len(hits) >= per_query_limit:
            break

    trace["recall_count"] = len(hits)
    candidates = [_hit_to_rerank_candidate(hit, retrieval_key=str(index)) for index, hit in enumerate(hits)]
    configured_rerank_top_n = int(settings.counseling_rerank_top_n)
    final_limit = min(safe_limit, configured_rerank_top_n) if configured_rerank_top_n > 0 else safe_limit
    if not candidates:
        trace["rerank_status"] = "empty"
        trace["rerank_reason"] = "no_candidates"
        trace["rerank_duration_ms"] = 0
        trace["rerank_scored_count"] = 0
        trace["status"] = "empty"
        trace["hit_count"] = 0
        trace["chunk_type_counts"] = {}
        trace["skipped_reason"] = "no_safe_examples"
        return _retrieval_result(trace=trace, started_at=started_at)

    rerank_result = await model_reranker.rerank(
        query=query,
        candidates=candidates,
        limit=final_limit,
        timeout_seconds=remaining_seconds(),
    )
    trace["rerank_status"] = rerank_result.status
    trace["rerank_reason"] = rerank_result.reason
    trace["rerank_duration_ms"] = rerank_result.duration_ms
    trace["rerank_scored_count"] = rerank_result.scored_count

    hit_by_retrieval_key = {
        str(candidate.metadata.get(RERANK_RETRIEVAL_KEY) or ""): hit for candidate, hit in zip(candidates, hits)
    }
    hit_by_chunk_id = {str(hit.entity.get("chunk_id") or hit.id or ""): hit for hit in hits}
    selected_hits: list[tuple[Any, RerankCandidate]] = []
    for candidate in rerank_result.candidates:
        retrieval_key = str(candidate.metadata.get(RERANK_RETRIEVAL_KEY) or "")
        hit = hit_by_retrieval_key.get(retrieval_key) or hit_by_chunk_id.get(candidate.chunk_id)
        if hit is not None:
            selected_hits.append((hit, candidate))

    examples: list[CounselingExampleHit] = []
    for hit, candidate in selected_hits[:safe_limit]:
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
                chunk_type=str(hit.entity.get("chunk_type") or "turn_pair"),
                original_external_id=str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or ""),
                phase=str(hit.entity.get("phase") or "") or None,
                display_text=str(hit.entity.get("display_text") or "") or None,
                process_quality_score=_to_float(hit.entity.get("process_quality_score")),
                rerank_score=candidate.rerank_score,
                rerank_reasons=list(candidate.rerank_reasons or []),
            )
        )
    trace["status"] = "hit" if examples else "empty"
    trace["hit_count"] = len(examples)
    chunk_type_counts: dict[str, int] = {}
    for example in examples:
        key = example.chunk_type or "turn_pair"
        chunk_type_counts[key] = chunk_type_counts.get(key, 0) + 1
    trace["chunk_type_counts"] = chunk_type_counts
    if not examples:
        trace["skipped_reason"] = "no_safe_examples"
    return _retrieval_result(examples=examples, trace=trace, started_at=started_at)


def _search_modes_for(mode: str) -> list[str | None]:
    normalized = (mode or "").strip().lower()
    if normalized == "companion":
        return [None, "vent", "soothe", "counseling"]
    if normalized == "vent":
        return ["vent", "soothe", None]
    if normalized == "soothe":
        return ["soothe", "vent", None]
    if normalized == "counseling":
        return ["counseling", "vent", None]
    return [normalized or None, None]


def _hit_to_rerank_candidate(hit: Any, *, retrieval_key: str) -> RerankCandidate:
    entity = dict(hit.entity or {})
    entity[RERANK_RETRIEVAL_KEY] = retrieval_key
    content = str(entity.get("content") or "").strip()
    display_text = str(entity.get("display_text") or "").strip()
    chunk_id = str(entity.get("chunk_id") or hit.id or "")
    vector_score = float(getattr(hit, "score", 0.0) or 0.0)
    return RerankCandidate(
        chunk_id=chunk_id,
        text=display_text or content,
        distance=1.0 - vector_score,
        metadata=entity,
        vector_score=vector_score,
        mode=str(entity.get("mode") or ""),
        chunk_type=_chunk_type_for_hit(hit),
        original_external_id=_original_external_id_for_hit(hit),
        source_key=str(entity.get("source_key") or ""),
        content=content,
        display_text=display_text,
    )


def _chunk_type_for_hit(hit: Any) -> str:
    chunk_type = str(hit.entity.get("chunk_type") or "").strip()
    return chunk_type if chunk_type in CHUNK_TYPES else "turn_pair"


def _original_external_id_for_hit(hit: Any) -> str:
    return str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or hit.id or "")


def _quota_for_state(state: AgentState, mode: str, limit: int) -> dict[str, int]:
    query = str(state.get("normalized_text") or state.get("user_text") or "")
    if any(pattern in query for pattern in CONTINUATION_PATTERNS):
        return {"session_sketch": 1, "process_segment": 1, "turn_pair": max(limit - 2, 0)}
    return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}


def _select_hits_by_quota(hits: list[Any], *, state: AgentState, mode: str, limit: int) -> list[Any]:
    quota = _quota_for_state(state, mode, limit)
    selected: list[Any] = []
    used_by_type = {chunk_type: 0 for chunk_type in quota}
    used_sources: dict[str, int] = {}

    for desired_type in quota:
        for hit in hits:
            if hit in selected:
                continue
            chunk_type = _chunk_type_for_hit(hit)
            if chunk_type != desired_type:
                continue
            if used_by_type[desired_type] >= quota[desired_type]:
                continue
            original_external_id = _original_external_id_for_hit(hit)
            if used_sources.get(original_external_id, 0) >= 2:
                continue
            selected.append(hit)
            used_by_type[desired_type] += 1
            used_sources[original_external_id] = used_sources.get(original_external_id, 0) + 1
            if len(selected) >= limit:
                return selected

    for hit in hits:
        if hit in selected:
            continue
        original_external_id = _original_external_id_for_hit(hit)
        if used_sources.get(original_external_id, 0) >= 2:
            continue
        selected.append(hit)
        used_sources[original_external_id] = used_sources.get(original_external_id, 0) + 1
        if len(selected) >= limit:
            break
    return selected


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
