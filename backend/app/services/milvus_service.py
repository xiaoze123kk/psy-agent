from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.embedding_service import embedding_client


logger = logging.getLogger(__name__)


KNOWLEDGE_COLLECTION_BASE = "knowledge_chunks_v1"
COUNSELING_COLLECTION_BASE = "counseling_examples_v1"


@dataclass(frozen=True)
class VectorHit:
    id: str
    score: float
    entity: dict[str, Any]


class MilvusVectorStore:
    def __init__(self) -> None:
        self.enabled = settings.milvus_enabled
        self.uri = settings.milvus_uri
        self.token = settings.milvus_token
        self.db_name = settings.milvus_db_name
        self.collection_prefix = settings.milvus_collection_prefix.strip("_")
        self.dim = settings.embedding_dim
        self._client: Any | None = None
        self._client_error: str | None = None

    @property
    def knowledge_collection(self) -> str:
        return self._collection_name(KNOWLEDGE_COLLECTION_BASE)

    @property
    def counseling_collection(self) -> str:
        return self._collection_name(COUNSELING_COLLECTION_BASE)

    @property
    def is_enabled(self) -> bool:
        return self.enabled and self.dim > 0

    def _collection_name(self, base: str) -> str:
        return f"{self.collection_prefix}_{base}" if self.collection_prefix else base

    def _get_client(self) -> Any | None:
        if not self.is_enabled:
            return None
        if self._client is not None:
            return self._client
        if self._client_error is not None:
            return None

        try:
            from pymilvus import MilvusClient
        except Exception as exc:  # pragma: no cover - depends on optional runtime package
            self._client_error = str(exc)
            logger.warning("PyMilvus is unavailable; vector search disabled: %s", exc)
            return None

        kwargs: dict[str, Any] = {"uri": self.uri}
        if self.token:
            kwargs["token"] = self.token
        if self.db_name and self.db_name != "default":
            kwargs["db_name"] = self.db_name

        try:
            self._client = MilvusClient(**kwargs)
        except TypeError:
            kwargs.pop("db_name", None)
            try:
                self._client = MilvusClient(**kwargs)
            except Exception as exc:  # pragma: no cover - requires Milvus runtime
                self._client_error = str(exc)
                logger.warning("Milvus connection failed: %s", exc)
                return None
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            self._client_error = str(exc)
            logger.warning("Milvus connection failed: %s", exc)
            return None

        return self._client

    def ensure_collections(self) -> bool:
        return self.ensure_knowledge_collection() and self.ensure_counseling_collection()

    def ensure_knowledge_collection(self) -> bool:
        return self._ensure_collection(
            self.knowledge_collection,
            extra_fields=[
                ("chunk_id", 80),
                ("article_id", 80),
                ("article_slug", 160),
                ("article_title", 220),
                ("category", 64),
                ("audience", 32),
                ("source_key", 80),
                ("source_name", 180),
                ("source_url", 1024),
                ("license", 160),
                ("status", 24),
                ("embedding_key", 256),
            ],
        )

    def ensure_counseling_collection(self) -> bool:
        return self._ensure_collection(
            self.counseling_collection,
            extra_fields=[
                ("chunk_id", 80),
                ("source_id", 80),
                ("source_key", 80),
                ("source_name", 180),
                ("external_id", 180),
                ("mode", 32),
                ("topic", 100),
                ("source_url", 1024),
                ("license", 160),
                ("status", 24),
                ("embedding_key", 256),
            ],
        )

    def _ensure_collection(self, collection_name: str, *, extra_fields: list[tuple[str, int]]) -> bool:
        client = self._get_client()
        if client is None:
            return False

        try:
            if client.has_collection(collection_name):
                self._load_collection(client, collection_name)
                return True
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus collection check failed for %s: %s", collection_name, exc)
            return False

        try:
            from pymilvus import DataType

            schema = client.create_schema(auto_id=False, enable_dynamic_fields=True)
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self.dim)
            schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=8192)
            for field_name, max_length in extra_fields:
                schema.add_field(field_name=field_name, datatype=DataType.VARCHAR, max_length=max_length)

            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
            self._load_collection(client, collection_name)
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus collection creation failed for %s: %s", collection_name, exc)
            return False
        return True

    @staticmethod
    def _load_collection(client: Any, collection_name: str) -> None:
        try:
            client.load_collection(collection_name)
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.debug("Milvus collection load skipped for %s: %s", collection_name, exc)

    def drop_collections(self, target: str = "all") -> dict[str, bool]:
        client = self._get_client()
        if client is None:
            return {}

        target_names = {
            "knowledge": [self.knowledge_collection],
            "counseling": [self.counseling_collection],
            "all": [self.knowledge_collection, self.counseling_collection],
        }.get(target, [self.knowledge_collection, self.counseling_collection])
        results: dict[str, bool] = {}
        for collection_name in target_names:
            try:
                if client.has_collection(collection_name):
                    client.drop_collection(collection_name)
                results[collection_name] = True
            except Exception as exc:  # pragma: no cover - requires Milvus runtime
                logger.warning("Milvus collection drop failed for %s: %s", collection_name, exc)
                results[collection_name] = False
        return results

    def list_indexed_chunk_ids(self, collection_name: str, *, limit: int = 10000) -> set[str]:
        client = self._get_client()
        if client is None:
            return set()

        filter_expr = f'embedding_key == "{self._escape_filter_value(embedding_client.embedding_key)}"'
        try:
            if not client.has_collection(collection_name):
                return set()
            rows = client.query(
                collection_name=collection_name,
                filter=filter_expr,
                output_fields=["chunk_id"],
                limit=limit,
            )
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus indexed id query failed for %s: %s", collection_name, exc)
            return set()

        ids: set[str] = set()
        for row in rows:
            chunk_id = str(row.get("chunk_id") or "").strip() if isinstance(row, dict) else ""
            if chunk_id:
                ids.add(chunk_id)
        return ids

    def upsert_knowledge_chunks(self, rows: list[dict[str, Any]]) -> bool:
        if not rows or not self.ensure_knowledge_collection():
            return False
        return self._upsert(self.knowledge_collection, rows)

    def upsert_counseling_examples(self, rows: list[dict[str, Any]]) -> bool:
        if not rows or not self.ensure_counseling_collection():
            return False
        return self._upsert(self.counseling_collection, rows)

    def _upsert(self, collection_name: str, rows: list[dict[str, Any]]) -> bool:
        client = self._get_client()
        if client is None:
            return False
        clean_rows = [self._clean_row(row) for row in rows]
        try:
            if hasattr(client, "upsert"):
                client.upsert(collection_name=collection_name, data=clean_rows)
            else:
                ids = [row["id"] for row in clean_rows]
                if ids:
                    expr = "id in [" + ",".join(f'"{item_id}"' for item_id in ids) + "]"
                    client.delete(collection_name=collection_name, filter=expr)
                client.insert(collection_name=collection_name, data=clean_rows)
            client.flush(collection_name)
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus upsert failed for %s: %s", collection_name, exc)
            return False
        return True

    def search_knowledge(self, vector: list[float], *, limit: int = 8) -> list[VectorHit]:
        if not self.ensure_knowledge_collection():
            return []
        filter_expr = f'status == "published" and embedding_key == "{self._escape_filter_value(embedding_client.embedding_key)}"'
        return self._search(
            self.knowledge_collection,
            vector,
            limit=limit,
            filter_expr=filter_expr,
            output_fields=[
                "chunk_id",
                "article_id",
                "article_slug",
                "article_title",
                "category",
                "audience",
                "source_key",
                "source_name",
                "source_url",
                "license",
                "embedding_key",
                "content",
            ],
        )

    def search_counseling_examples(
        self,
        vector: list[float],
        *,
        mode: str | None = None,
        limit: int = 5,
    ) -> list[VectorHit]:
        if not self.ensure_counseling_collection():
            return []
        filter_expr = f'status == "published" and embedding_key == "{self._escape_filter_value(embedding_client.embedding_key)}"'
        if mode:
            filter_expr += f' and mode in ["{mode}", "companion", "counseling"]'
        return self._search(
            self.counseling_collection,
            vector,
            limit=limit,
            filter_expr=filter_expr,
            output_fields=[
                "chunk_id",
                "source_id",
                "source_key",
                "source_name",
                "external_id",
                "mode",
                "topic",
                "source_url",
                "license",
                "embedding_key",
                "content",
            ],
        )

    def _search(
        self,
        collection_name: str,
        vector: list[float],
        *,
        limit: int,
        filter_expr: str,
        output_fields: list[str],
    ) -> list[VectorHit]:
        client = self._get_client()
        if client is None:
            return []
        if len(vector) != self.dim:
            logger.warning("Milvus query vector dimension mismatch: expected %s, got %s", self.dim, len(vector))
            return []

        try:
            raw_results = client.search(
                collection_name=collection_name,
                data=[vector],
                filter=filter_expr,
                limit=limit,
                output_fields=output_fields,
                search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            )
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus search failed for %s: %s", collection_name, exc)
            return []

        first = raw_results[0] if raw_results else []
        hits: list[VectorHit] = []
        for item in first:
            entity = dict(item.get("entity") or {}) if isinstance(item, dict) else {}
            item_id = str(item.get("id") or entity.get("id") or "") if isinstance(item, dict) else ""
            distance = item.get("distance", item.get("score", 0.0)) if isinstance(item, dict) else 0.0
            try:
                score = float(distance)
            except (TypeError, ValueError):
                score = 0.0
            if item_id:
                hits.append(VectorHit(id=item_id, score=score, entity=entity))
        return hits

    @staticmethod
    def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in row.items():
            if value is None:
                cleaned[key] = ""
            elif isinstance(value, str):
                cleaned[key] = value[:8192] if key == "content" else value
            elif key != "vector":
                cleaned[key] = str(value)
            else:
                cleaned[key] = value
        return cleaned

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


milvus_store = MilvusVectorStore()
