from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import CounselingCorpusSource, CounselingExampleChunk, KnowledgeArticle, KnowledgeChunk
from app.services.counseling_vector_service import counseling_chunk_to_vector_row
from app.services.embedding_service import embedding_client
from app.services.milvus_service import milvus_store


@dataclass(frozen=True)
class IndexCounts:
    indexed: int
    skipped: int


def knowledge_chunk_to_vector_row(
    chunk: KnowledgeChunk,
    article: KnowledgeArticle,
    vector: list[float],
) -> dict[str, object]:
    source = article.source
    return {
        "id": chunk.id,
        "chunk_id": chunk.id,
        "article_id": article.id,
        "article_slug": article.slug,
        "article_title": article.title,
        "category": article.category,
        "audience": article.audience,
        "source_key": source.source_key if source else "internal_curated",
        "source_name": source.name if source else "内部审核心理知识种子库",
        "source_url": chunk.source_url or article.source_url or (source.base_url if source else ""),
        "license": chunk.license or article.license or (source.license if source else "internal-curated"),
        "status": chunk.status,
        "embedding_key": embedding_client.embedding_key,
        "content": chunk.content,
        "vector": vector,
    }


async def index_knowledge_chunks(
    db: Session,
    *,
    limit: int | None = None,
    batch_size: int = 10,
    missing_only: bool = False,
) -> IndexCounts:
    if not milvus_store.ensure_knowledge_collection():
        return IndexCounts(indexed=0, skipped=0)

    query = (
        select(KnowledgeChunk, KnowledgeArticle)
        .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
        .options(joinedload(KnowledgeArticle.source))
        .where(
            KnowledgeArticle.status == "published",
            KnowledgeArticle.review_status == "published",
            KnowledgeChunk.status == "published",
        )
        .order_by(KnowledgeArticle.updated_at.desc(), KnowledgeChunk.chunk_index.asc())
    )
    if missing_only:
        indexed_ids = milvus_store.list_indexed_chunk_ids(milvus_store.knowledge_collection)
        if indexed_ids:
            query = query.where(~KnowledgeChunk.id.in_(indexed_ids))
    if limit:
        query = query.limit(limit)

    rows = [(chunk, article) for chunk, article in db.execute(query).all()]
    indexed = 0
    skipped = 0
    for index in range(0, len(rows), batch_size):
        batch = rows[index : index + batch_size]
        texts = [chunk.content for chunk, _ in batch]
        vectors = await embedding_client.embed_texts(texts)
        if vectors is None:
            skipped += len(batch)
            continue
        payload = [
            knowledge_chunk_to_vector_row(chunk, article, vector)
            for (chunk, article), vector in zip(batch, vectors)
        ]
        if milvus_store.upsert_knowledge_chunks(payload):
            indexed += len(payload)
        else:
            skipped += len(payload)
    return IndexCounts(indexed=indexed, skipped=skipped)


async def index_counseling_chunks(
    db: Session,
    *,
    source_key: str | None = None,
    limit: int | None = None,
    batch_size: int = 10,
    missing_only: bool = False,
) -> IndexCounts:
    if not milvus_store.ensure_counseling_collection():
        return IndexCounts(indexed=0, skipped=0)

    query = (
        select(CounselingExampleChunk)
        .options(joinedload(CounselingExampleChunk.source))
        .where(CounselingExampleChunk.status == "published")
        .order_by(CounselingExampleChunk.updated_at.desc())
    )
    if source_key:
        query = query.join(CounselingCorpusSource).where(CounselingCorpusSource.source_key == source_key)
    if missing_only:
        indexed_ids = milvus_store.list_indexed_chunk_ids(milvus_store.counseling_collection)
        if indexed_ids:
            query = query.where(~CounselingExampleChunk.id.in_(indexed_ids))
    if limit:
        query = query.limit(limit)

    chunks = list(db.scalars(query))
    indexed = 0
    skipped = 0
    for index in range(0, len(chunks), batch_size):
        batch = chunks[index : index + batch_size]
        texts = [chunk.content for chunk in batch]
        vectors = await embedding_client.embed_texts(texts)
        if vectors is None:
            skipped += len(batch)
            continue
        payload = [
            counseling_chunk_to_vector_row(chunk, chunk.source, vector)
            for chunk, vector in zip(batch, vectors)
        ]
        if milvus_store.upsert_counseling_examples(payload):
            indexed += len(payload)
        else:
            skipped += len(payload)
    return IndexCounts(indexed=indexed, skipped=skipped)
