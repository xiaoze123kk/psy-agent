from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import milvus_service
from app.services import knowledge_service
from app.db.models import Base
from app.services.embedding_service import EmbeddingClient
from app.services.milvus_service import MilvusVectorStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class FakeBGEM3FlagModel:
    init_args: tuple[object, ...] = ()
    init_kwargs: dict[str, object] = {}
    encode_calls: list[dict[str, object]] = []
    vector_dim = 1024

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).init_args = args
        type(self).init_kwargs = kwargs

    def encode(self, texts: list[str], **kwargs: object) -> dict[str, list[list[float]]]:
        type(self).encode_calls.append({"texts": texts, **kwargs})
        return {
            "dense_vecs": [
                [float(index + 1)] * type(self).vector_dim
                for index, _ in enumerate(texts)
            ]
        }


def _make_local_client() -> EmbeddingClient:
    client = EmbeddingClient()
    client.provider = "local"
    client.model = "BAAI/bge-m3"
    client.dim = 1024
    client.local_device = "cpu"
    client.local_batch_size = 2
    client.local_max_length = 32
    client.local_use_fp16 = "false"
    client.local_cache_dir = None
    client._local_model = None
    client._local_model_error = None
    return client


class EmbeddingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeBGEM3FlagModel.init_args = ()
        FakeBGEM3FlagModel.init_kwargs = {}
        FakeBGEM3FlagModel.encode_calls = []
        FakeBGEM3FlagModel.vector_dim = 1024

    async def test_local_provider_uses_bge_m3_dense_vectors(self) -> None:
        original_module = sys.modules.get("FlagEmbedding")
        sys.modules["FlagEmbedding"] = SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
        try:
            client = _make_local_client()
            vectors = await client.embed_texts(["焦虑", "失眠"])
        finally:
            if original_module is None:
                sys.modules.pop("FlagEmbedding", None)
            else:
                sys.modules["FlagEmbedding"] = original_module

        self.assertEqual(len(vectors or []), 2)
        self.assertEqual(len(vectors[0]), 1024)
        self.assertEqual(FakeBGEM3FlagModel.init_args, ("BAAI/bge-m3",))
        self.assertEqual(FakeBGEM3FlagModel.init_kwargs["devices"], "cpu")
        self.assertEqual(FakeBGEM3FlagModel.init_kwargs["use_fp16"], False)
        self.assertNotIn("batch_size", FakeBGEM3FlagModel.init_kwargs)
        self.assertNotIn("return_dense", FakeBGEM3FlagModel.init_kwargs)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["batch_size"], 2)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["max_length"], 32)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["return_dense"], True)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["return_sparse"], False)

    async def test_local_provider_rejects_dimension_mismatch(self) -> None:
        FakeBGEM3FlagModel.vector_dim = 2
        original_module = sys.modules.get("FlagEmbedding")
        sys.modules["FlagEmbedding"] = SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
        try:
            client = _make_local_client()
            vectors = await client.embed_texts(["焦虑"])
        finally:
            if original_module is None:
                sys.modules.pop("FlagEmbedding", None)
            else:
                sys.modules["FlagEmbedding"] = original_module

        self.assertIsNone(vectors)

    async def test_missing_local_dependency_degrades_to_no_vectors(self) -> None:
        original_module = sys.modules.pop("FlagEmbedding", None)
        real_import = __import__

        def fake_import(name: str, *args: object, **kwargs: object):
            if name == "FlagEmbedding":
                raise ImportError("missing FlagEmbedding")
            return real_import(name, *args, **kwargs)

        try:
            client = _make_local_client()
            with patch("builtins.__import__", side_effect=fake_import):
                vectors = await client.embed_texts(["焦虑"])
        finally:
            if original_module is not None:
                sys.modules["FlagEmbedding"] = original_module

        self.assertIsNone(vectors)


class MilvusEmbeddingKeyTests(unittest.TestCase):
    def test_knowledge_search_filters_current_embedding_key(self) -> None:
        original_provider = milvus_service.embedding_client.provider
        original_model = milvus_service.embedding_client.model
        original_dim = milvus_service.embedding_client.dim
        milvus_service.embedding_client.provider = "local"
        milvus_service.embedding_client.model = "BAAI/bge-m3"
        milvus_service.embedding_client.dim = 1024
        try:
            store = MilvusVectorStore()
            captured: dict[str, object] = {}

            def fake_search_rest(*args: object, **kwargs: object) -> list[object]:
                captured.update(kwargs)
                return []

            store._search_rest = fake_search_rest  # type: ignore[method-assign]
            store.search_knowledge([0.1] * store.dim)
        finally:
            milvus_service.embedding_client.provider = original_provider
            milvus_service.embedding_client.model = original_model
            milvus_service.embedding_client.dim = original_dim

        self.assertIn('embedding_key == "local:BAAI/bge-m3:1024"', str(captured["filter_expr"]))


class SemanticSearchGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_milvus_skips_knowledge_embedding(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_enabled = knowledge_service.milvus_store.enabled
        original_embed_query = knowledge_service.embedding_client.embed_query

        async def fail_if_called(text: str):
            raise AssertionError("disabled Milvus must not call embedding retrieval")

        knowledge_service.milvus_store.enabled = False
        knowledge_service.embedding_client.embed_query = fail_if_called
        try:
            with Session() as db:
                hits = await knowledge_service._search_chunk_hits_semantic(db, query="焦虑怎么办")
        finally:
            knowledge_service.milvus_store.enabled = original_enabled
            knowledge_service.embedding_client.embed_query = original_embed_query

        self.assertEqual(hits, [])
