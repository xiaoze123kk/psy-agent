from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


def counseling_chunk_to_vector_row(
    chunk: CounselingExampleChunk,
    source: CounselingCorpusSource,
    vector: list[float],
) -> dict[str, object]:
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
        "vector": vector,
    }


async def retrieve_counseling_examples(
    state: AgentState,
    *,
    mode: str,
    limit: int = 5,
) -> list[CounselingExampleHit]:
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
    per_query_limit = max(limit * 2, 6)
    for search_mode in search_modes:
        for hit in milvus_store.search_counseling_examples(vector, mode=search_mode, limit=per_query_limit):
            if hit.id in seen_ids:
                continue
            seen_ids.add(hit.id)
            hits.append(hit)
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    examples: list[CounselingExampleHit] = []
    for hit in hits[:limit]:
        content = str(hit.entity.get("content") or "").strip()
        if not content:
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
