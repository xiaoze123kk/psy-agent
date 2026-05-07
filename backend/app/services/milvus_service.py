from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.embedding_service import embedding_client


logger = logging.getLogger(__name__)


KNOWLEDGE_COLLECTION_BASE = "knowledge_chunks_v1"
COUNSELING_COLLECTION_BASE = "counseling_examples_v1"


def _patch_pymilvus_connect_timeout() -> None:
    try:
        from pymilvus.client import grpc_handler as grpc_handler_module
    except Exception:  # pragma: no cover - optional runtime package
        return

    handler_cls = grpc_handler_module.GrpcHandler
    if getattr(handler_cls, "_psych_agent_timeout_patch", False):
        return

    def _patched_internal_register(self: Any, user: str, host: str, **kwargs) -> int:
        request = grpc_handler_module.Prepare.register_request(user, host)
        response = self._stub.Connect(request=request, timeout=kwargs.get("timeout"))
        grpc_handler_module.check_status(response.status)
        return response.identifier

    def _patched_setup_identifier_interceptor(self: Any, user: str, timeout: int = 10) -> None:
        self._identifier = None
        if getattr(self, "_stub", None) is None:
            self._stub = grpc_handler_module.milvus_pb2_grpc.MilvusServiceStub(self._final_channel)

    setattr(handler_cls, "_GrpcHandler__internal_register", _patched_internal_register)
    setattr(handler_cls, "_setup_identifier_interceptor", _patched_setup_identifier_interceptor)
    setattr(handler_cls, "_psych_agent_timeout_patch", True)


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
        self.connect_timeout_seconds = max(settings.milvus_connect_timeout_seconds, 0.2)
        self.request_timeout_seconds = max(self.connect_timeout_seconds * 4, 5.0)
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

    @property
    def is_available(self) -> bool:
        return self.is_enabled and self._endpoint_reachable()

    def _collection_name(self, base: str) -> str:
        return f"{self.collection_prefix}_{base}" if self.collection_prefix else base

    def _rest_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _rest_base_url(self) -> str:
        parsed = urlparse(self.uri)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port
        if host in {"localhost", "::1"}:
            host = "127.0.0.1"
        if port:
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"

    def _search_rest(
        self,
        collection_name: str,
        vector: list[float],
        *,
        limit: int,
        filter_expr: str,
        output_fields: list[str],
    ) -> list[VectorHit] | None:
        if not self._endpoint_reachable():
            return []
        if len(vector) != self.dim:
            return []

        payload: dict[str, Any] = {
            "dbName": self.db_name or "default",
            "collectionName": collection_name,
            "data": [vector],
            "annsField": "vector",
            "limit": limit,
            "filter": filter_expr,
            "outputFields": output_fields,
            "searchParams": {"metric_type": "COSINE", "params": {"ef": 64}},
        }
        endpoint = self._rest_base_url().rstrip("/") + "/v2/vectordb/entities/search"

        try:
            with httpx.Client(timeout=self.request_timeout_seconds, trust_env=False) as client:
                response = client.post(
                    endpoint,
                    headers=self._rest_headers(),
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Milvus REST search failed for %s: %s", collection_name, exc)
            return None

        try:
            data = response.json()
        except ValueError:
            logger.warning("Milvus REST search returned invalid JSON for %s", collection_name)
            return None

        if not isinstance(data, dict) or int(data.get("code", -1)) != 0:
            logger.warning("Milvus REST search returned error for %s: %s", collection_name, data)
            return None

        rows = data.get("data")
        if not isinstance(rows, list):
            return []

        hits: list[VectorHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id") or "")
            entity = {field: row.get(field) for field in output_fields}
            entity["id"] = item_id
            try:
                score = float(row.get("distance", row.get("score", 0.0)) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if item_id:
                hits.append(VectorHit(id=item_id, score=score, entity=entity))
        return hits

    def _endpoint_reachable(self) -> bool:
        parsed = urlparse(self.uri)
        host = parsed.hostname
        port = parsed.port
        if not host:
            normalized = self.uri.replace("tcp://", "").replace("http://", "").replace("https://", "")
            if ":" in normalized:
                host, raw_port = normalized.rsplit(":", 1)
                try:
                    port = int(raw_port)
                except ValueError:
                    port = None
        if not host or not port:
            return True

        try:
            with socket.create_connection((host, port), timeout=self.connect_timeout_seconds):
                return True
        except OSError:
            if self._client is not None:
                self._client = None
            return False

    def _get_client(self) -> Any | None:
        if not self.is_enabled:
            return None
        if not self._endpoint_reachable():
            return None
        if self._client is not None:
            return self._client

        try:
            from pymilvus import MilvusClient
        except Exception as exc:  # pragma: no cover - depends on optional runtime package
            self._client_error = str(exc)
            logger.warning("PyMilvus is unavailable; vector search disabled: %s", exc)
            return None

        _patch_pymilvus_connect_timeout()

        kwargs: dict[str, Any] = {"uri": self.uri, "timeout": self.request_timeout_seconds}
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
        if not self._endpoint_reachable():
            return False
        client = self._get_client()
        if client is None:
            return False

        try:
            if client.has_collection(collection_name, timeout=self.request_timeout_seconds):
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
                timeout=self.request_timeout_seconds,
            )
            self._load_collection(client, collection_name)
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus collection creation failed for %s: %s", collection_name, exc)
            return False
        return True

    @staticmethod
    def _load_collection(client: Any, collection_name: str) -> None:
        try:
            client.load_collection(collection_name, timeout=5.0)
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
                if client.has_collection(collection_name, timeout=self.request_timeout_seconds):
                    client.drop_collection(collection_name, timeout=self.request_timeout_seconds)
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
            if not client.has_collection(collection_name, timeout=self.request_timeout_seconds):
                return set()
            rows = client.query(
                collection_name=collection_name,
                filter=filter_expr,
                output_fields=["chunk_id"],
                limit=limit,
                timeout=self.request_timeout_seconds,
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
        if not self._endpoint_reachable():
            return False
        client = self._get_client()
        if client is None:
            return False
        clean_rows = [self._clean_row(row) for row in rows]
        try:
            if hasattr(client, "upsert"):
                client.upsert(
                    collection_name=collection_name,
                    data=clean_rows,
                    timeout=self.request_timeout_seconds,
                )
            else:
                ids = [row["id"] for row in clean_rows]
                if ids:
                    expr = "id in [" + ",".join(f'"{item_id}"' for item_id in ids) + "]"
                    client.delete(collection_name=collection_name, filter=expr, timeout=self.request_timeout_seconds)
                client.insert(collection_name=collection_name, data=clean_rows, timeout=self.request_timeout_seconds)
            client.flush(collection_name, timeout=self.request_timeout_seconds)
        except Exception as exc:  # pragma: no cover - requires Milvus runtime
            logger.warning("Milvus upsert failed for %s: %s", collection_name, exc)
            return False
        return True

    def search_knowledge(self, vector: list[float], *, limit: int = 8) -> list[VectorHit]:
        filter_expr = f'status == "published" and embedding_key == "{self._escape_filter_value(embedding_client.embedding_key)}"'
        rest_hits = self._search_rest(
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
        if rest_hits is not None:
            return rest_hits
        if not self.ensure_knowledge_collection():
            return []
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
        filter_expr = f'status == "published" and embedding_key == "{self._escape_filter_value(embedding_client.embedding_key)}"'
        if mode:
            filter_expr += f' and mode == "{self._escape_filter_value(mode)}"'
        rest_hits = self._search_rest(
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
        if rest_hits is not None:
            return rest_hits
        if not self.ensure_counseling_collection():
            return []
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
        if not self._endpoint_reachable():
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
                timeout=self.request_timeout_seconds,
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
