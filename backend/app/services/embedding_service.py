from __future__ import annotations

import asyncio
import logging
from threading import Lock
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self) -> None:
        self.provider = settings.embedding_provider.lower()
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self.local_device = settings.local_embedding_device
        self.local_batch_size = max(settings.local_embedding_batch_size, 1)
        self.local_max_length = max(settings.local_embedding_max_length, 1)
        self.local_use_fp16 = settings.local_embedding_use_fp16.lower()
        self.local_cache_dir = settings.local_embedding_cache_dir
        self.dashscope_api_key = settings.dashscope_api_key
        self.dashscope_base_url = settings.dashscope_base_url.rstrip("/")
        self.timeout_seconds = settings.embedding_timeout_seconds
        self._local_model: Any | None = None
        self._local_model_error: str | None = None
        self._local_model_lock = Lock()

    @property
    def embedding_key(self) -> str:
        return f"{self.provider}:{self.model}:{self.dim}"

    @property
    def is_configured(self) -> bool:
        if not self.model or self.dim <= 0:
            return False
        if self.provider == "local":
            return True
        if self.provider == "dashscope":
            return bool(self.dashscope_api_key)
        return False

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        cleaned = [text.strip() for text in texts if text and text.strip()]
        if not cleaned or not self.is_configured:
            return None

        if self.provider == "local":
            return await self._embed_local_texts(cleaned)
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
        vectors = await self.embed_texts([text])
        if not vectors:
            return None
        return vectors[0]

    async def _embed_local_texts(self, texts: list[str]) -> list[list[float]] | None:
        return await asyncio.to_thread(self._embed_local_texts_sync, texts)

    def _embed_local_texts_sync(self, texts: list[str]) -> list[list[float]] | None:
        model = self._get_local_model()
        if model is None:
            return None

        try:
            output = model.encode(
                texts,
                batch_size=self.local_batch_size,
                max_length=self.local_max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            logger.warning("Local embedding request failed: %s", exc)
            return None

        dense_vectors = output.get("dense_vecs") if isinstance(output, dict) else output
        return self._coerce_vectors(dense_vectors, expected_count=len(texts))

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
