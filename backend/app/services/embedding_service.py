from __future__ import annotations

import asyncio
from collections import OrderedDict
import json
import logging
import os
import sys
from threading import Lock
from typing import Any

import httpx

from app.core.config import BASE_DIR, settings


logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self.provider = settings.embedding_provider.lower()
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self.index_version = settings.embedding_index_version
        self.local_device = settings.local_embedding_device
        self.local_batch_size = max(settings.local_embedding_batch_size, 1)
        self.local_max_length = max(settings.local_embedding_max_length, 1)
        self.local_query_max_length = max(settings.local_embedding_query_max_length, 1)
        self.local_document_max_length = max(settings.local_embedding_document_max_length, 1)
        self.local_use_fp16 = settings.local_embedding_use_fp16.lower()
        self.local_cache_dir = settings.local_embedding_cache_dir
        self.dashscope_api_key = settings.dashscope_api_key
        self.dashscope_base_url = settings.dashscope_base_url.rstrip("/")
        self.timeout_seconds = settings.embedding_timeout_seconds
        self.query_cache_size = max(settings.embedding_query_cache_size, 0)
        self._local_model: Any | None = None
        self._local_model_error: str | None = None
        self._local_model_lock = Lock()
        self._local_worker_process: Any | None = None
        self._local_worker_lock: asyncio.Lock | None = None
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._query_cache_lock = Lock()

    @property
    def embedding_key(self) -> str:
        base = f"{self.provider}:{self.model}:{self.dim}"
        return f"{base}:{self.index_version}" if self.index_version else base

    @property
    def resolved_local_device(self) -> str:
        if self.provider != "local":
            return ""
        return self._resolve_local_device()

    @property
    def is_configured(self) -> bool:
        if not self.model or self.dim <= 0:
            return False
        if self.provider == "local":
            return True
        if self.provider == "dashscope":
            return bool(self.dashscope_api_key)
        return False

    def is_safe_for_realtime(self) -> bool:
        """Whether this embedding backend is safe to run inside the API process."""
        override = os.getenv("LOCAL_EMBEDDING_ALLOW_UNSAFE_IN_PROCESS", "").strip().lower()
        if override in {"1", "true", "yes", "on"}:
            return True
        if self.provider == "local" and os.name == "nt" and sys.version_info >= (3, 13):
            return False
        return True

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]] | None:
        return await self._embed_texts(texts, kind="document")

    async def _embed_texts(self, texts: list[str], *, kind: str) -> list[list[float]] | None:
        cleaned = [text.strip() for text in texts if text and text.strip()]
        if not cleaned or not self.is_configured:
            return None

        if self.provider == "local":
            return await self._embed_local_texts(cleaned, kind=kind)
        if self.provider != "dashscope":
            logger.warning("Unsupported embedding provider: %s", self.provider)
            return None

        vectors: list[list[float]] = []
        for index in range(0, len(cleaned), 10):
            batch = cleaned[index : index + 10]
            batch_vectors = await self._embed_dashscope_batch(batch)
            if batch_vectors is None:
                return None
            vectors.extend(batch_vectors)
        return vectors

    async def embed_query(self, text: str) -> list[float] | None:
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        cache_key = self._query_cache_key(cleaned)
        cached = self._get_cached_query_vector(cache_key)
        if cached is not None:
            return cached

        vectors = await self._embed_texts([cleaned], kind="query")
        if not vectors:
            return None
        vector = vectors[0]
        self._store_cached_query_vector(cache_key, vector)
        return list(vector)

    async def warmup(self) -> bool:
        vector = await self.embed_query("RAG warmup")
        return vector is not None

    async def _embed_local_texts(self, texts: list[str], *, kind: str) -> list[list[float]] | None:
        if self._use_local_worker():
            return await self._embed_local_texts_with_worker(texts, kind=kind)
        return await asyncio.to_thread(self._embed_local_texts_sync, texts, kind=kind)

    async def _embed_local_texts_with_worker(self, texts: list[str], *, kind: str) -> list[list[float]] | None:
        lock = self._get_local_worker_lock()
        async with lock:
            process = await self._ensure_local_worker()
            if process is None or process.stdin is None or process.stdout is None:
                return None

            payload = json.dumps({"texts": texts, "kind": kind}, ensure_ascii=True).encode("ascii") + b"\n"
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
                timeout_seconds = max(self.timeout_seconds, settings.rag_retrieval_timeout_seconds)
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout_seconds)
            except (BrokenPipeError, ConnectionError, asyncio.TimeoutError) as exc:
                logger.warning("Local embedding worker request failed: %s", exc)
                await self._stop_local_worker()
                return None

            if not line:
                logger.warning("Local embedding worker exited before returning vectors.")
                await self._stop_local_worker()
                return None

            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning("Local embedding worker returned invalid JSON: %s", exc)
                await self._stop_local_worker()
                return None

            if not isinstance(response, dict) or not response.get("ok"):
                logger.warning("Local embedding worker failed: %s", response)
                await self._stop_local_worker()
                return None

            return self._coerce_vectors(response.get("vectors"), expected_count=len(texts))

    async def aclose(self) -> None:
        await self._stop_local_worker()

    def _embed_local_texts_sync(self, texts: list[str], *, kind: str) -> list[list[float]] | None:
        model = self._get_local_model()
        if model is None:
            return None

        try:
            max_length = self._local_max_length_for_kind(kind)
            encode_kwargs = {
                "batch_size": self.local_batch_size,
                "max_length": max_length,
                "return_dense": True,
                "return_sparse": False,
                "return_colbert_vecs": False,
            }
            if kind == "query" and hasattr(model, "encode_queries"):
                output = model.encode_queries(texts, **encode_kwargs)
            else:
                output = model.encode(texts, **encode_kwargs)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            logger.warning("Local embedding request failed: %s", exc)
            return None

        dense_vectors = output.get("dense_vecs") if isinstance(output, dict) else output
        return self._coerce_vectors(dense_vectors, expected_count=len(texts))

    def _local_max_length_for_kind(self, kind: str) -> int:
        if kind == "query":
            return self.local_query_max_length
        if kind == "document":
            return self.local_document_max_length
        return self.local_max_length

    def _get_local_model(self) -> Any | None:
        if self._local_model is not None:
            return self._local_model
        if self._local_model_error is not None:
            return None

        with self._local_model_lock:
            if self._local_model is not None:
                return self._local_model
            if self._local_model_error is not None:
                return None

            try:
                from FlagEmbedding import BGEM3FlagModel
            except Exception as exc:  # pragma: no cover - optional dependency
                self._local_model_error = str(exc)
                logger.warning(
                    "FlagEmbedding is unavailable; install requirements-local-embedding.txt to enable local embeddings: %s",
                    exc,
                )
                return None

            device = self._resolve_local_device()
            use_fp16 = self._resolve_local_use_fp16(device)
            kwargs: dict[str, Any] = {
                "use_fp16": use_fp16,
                "devices": device,
            }
            if self.local_cache_dir:
                kwargs["cache_dir"] = self.local_cache_dir

            try:
                self._local_model = BGEM3FlagModel(self.model, **kwargs)
            except Exception as exc:  # pragma: no cover - depends on optional model runtime
                self._local_model_error = str(exc)
                logger.warning("Local embedding model load failed: %s", exc)
                return None
            return self._local_model

    def _resolve_local_device(self) -> str:
        configured = (self.local_device or "auto").strip().lower()
        if configured != "auto":
            return configured
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _resolve_local_use_fp16(self, device: str) -> bool:
        configured = (self.local_use_fp16 or "auto").strip().lower()
        if configured in {"1", "true", "yes", "on"}:
            return True
        if configured in {"0", "false", "no", "off"}:
            return False
        return device.startswith("cuda")

    def _use_local_worker(self) -> bool:
        configured = os.getenv("LOCAL_EMBEDDING_USE_WORKER", "auto").strip().lower()
        if configured in {"1", "true", "yes", "on"}:
            return True
        if configured in {"0", "false", "no", "off"}:
            return False
        return not self.is_safe_for_realtime()

    def _get_local_worker_lock(self) -> asyncio.Lock:
        if self._local_worker_lock is None:
            self._local_worker_lock = asyncio.Lock()
        return self._local_worker_lock

    async def _ensure_local_worker(self) -> Any | None:
        if self._local_worker_process is not None and self._local_worker_process.returncode is None:
            return self._local_worker_process

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["LOCAL_EMBEDDING_WORKER_MODE"] = "1"
        try:
            self._local_worker_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.services.local_embedding_worker",
                cwd=str(BASE_DIR),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=8 * 1024 * 1024,
            )
        except Exception as exc:  # pragma: no cover - process startup depends on host runtime
            logger.warning("Local embedding worker start failed: %s", exc)
            self._local_worker_process = None
        return self._local_worker_process

    async def _stop_local_worker(self) -> None:
        process = self._local_worker_process
        self._local_worker_process = None
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3)
        except Exception:  # pragma: no cover - defensive cleanup
            try:
                process.kill()
            except Exception:
                pass

    def _query_cache_key(self, text: str) -> str:
        return f"{self.embedding_key}:{text}"

    def _get_cached_query_vector(self, key: str) -> list[float] | None:
        if self.query_cache_size <= 0:
            return None
        with self._query_cache_lock:
            vector = self._query_cache.get(key)
            if vector is None:
                return None
            self._query_cache.move_to_end(key)
            return list(vector)

    def _store_cached_query_vector(self, key: str, vector: list[float]) -> None:
        if self.query_cache_size <= 0:
            return
        with self._query_cache_lock:
            self._query_cache[key] = list(vector)
            self._query_cache.move_to_end(key)
            while len(self._query_cache) > self.query_cache_size:
                self._query_cache.popitem(last=False)

    async def _embed_dashscope_batch(self, texts: list[str]) -> list[list[float]] | None:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "dimensions": self.dim,
        }
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.dashscope_base_url}/embeddings",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Embedding request failed: %s", exc)
            return None

        data = response.json()
        items = data.get("data")
        if not isinstance(items, list):
            return None

        indexed_vectors: list[tuple[int, Any]] = []
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            embedding = item.get("embedding")
            if embedding is None:
                continue
            try:
                item_index = int(item.get("index", position))
            except (TypeError, ValueError):
                item_index = position
            indexed_vectors.append((item_index, embedding))

        indexed_vectors.sort(key=lambda item: item[0])
        return self._coerce_vectors([vector for _, vector in indexed_vectors], expected_count=len(texts))

    def _coerce_vectors(self, raw_vectors: Any, *, expected_count: int) -> list[list[float]] | None:
        if hasattr(raw_vectors, "tolist"):
            raw_vectors = raw_vectors.tolist()
        if not isinstance(raw_vectors, list):
            return None
        if len(raw_vectors) != expected_count:
            logger.warning("Embedding response count mismatch: expected %s, got %s", expected_count, len(raw_vectors))
            return None

        vectors: list[list[float]] = []
        for raw_vector in raw_vectors:
            if hasattr(raw_vector, "tolist"):
                raw_vector = raw_vector.tolist()
            if not isinstance(raw_vector, (list, tuple)):
                return None
            vector = [float(value) for value in raw_vector]
            if len(vector) != self.dim:
                logger.warning("Embedding dimension mismatch: expected %s, got %s", self.dim, len(vector))
                return None
            vectors.append(vector)
        return vectors


embedding_client = EmbeddingClient()
