from __future__ import annotations

import sys
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import milvus_service
from app.services import knowledge_service
from app.services import vector_index_service
from app.db.models import Base
from app.db.models import CounselingCorpusSource, CounselingExampleChunk, KnowledgeArticle, KnowledgeChunk
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
    client.index_version = ""
    client.local_device = "cpu"
    client.local_batch_size = 2
    client.local_max_length = 32
    client.local_query_max_length = 16
    client.local_document_max_length = 64
    client.local_use_fp16 = "false"
    client.local_cache_dir = None
    client._local_model = None
    client._local_model_error = None
    client.is_safe_for_realtime = lambda: True  # type: ignore[method-assign]
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
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["kind"], "document")
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["max_length"], 64)
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

    async def test_embed_query_reuses_cached_vector_for_same_text(self) -> None:
        original_module = sys.modules.get("FlagEmbedding")
        sys.modules["FlagEmbedding"] = SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
        try:
            client = _make_local_client()
            first = await client.embed_query("same query")
            second = await client.embed_query(" same query ")
        finally:
            if original_module is None:
                sys.modules.pop("FlagEmbedding", None)
            else:
                sys.modules["FlagEmbedding"] = original_module

        self.assertEqual(first, second)
        self.assertEqual(len(FakeBGEM3FlagModel.encode_calls), 1)

    async def test_local_provider_uses_separate_query_and_document_lengths(self) -> None:
        original_module = sys.modules.get("FlagEmbedding")
        sys.modules["FlagEmbedding"] = SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
        try:
            client = _make_local_client()
            await client.embed_query("查询文本")
            await client.embed_documents(["文档片段"])
        finally:
            if original_module is None:
                sys.modules.pop("FlagEmbedding", None)
            else:
                sys.modules["FlagEmbedding"] = original_module

        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["kind"], "query")
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["max_length"], 16)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[1]["kind"], "document")
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[1]["max_length"], 64)

    async def test_embedding_key_includes_index_version_when_configured(self) -> None:
        client = _make_local_client()
        client.index_version = "rag-layered-v1"

        self.assertEqual(client.embedding_key, "local:BAAI/bge-m3:1024:rag-layered-v1")

    async def test_warmup_loads_local_embedding_model(self) -> None:
        original_module = sys.modules.get("FlagEmbedding")
        sys.modules["FlagEmbedding"] = SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
        try:
            client = _make_local_client()
            warmed = await client.warmup()
        finally:
            if original_module is None:
                sys.modules.pop("FlagEmbedding", None)
            else:
                sys.modules["FlagEmbedding"] = original_module

        self.assertTrue(warmed)
        self.assertEqual(len(FakeBGEM3FlagModel.encode_calls), 1)
        self.assertEqual(FakeBGEM3FlagModel.encode_calls[0]["texts"], ["RAG warmup"])

    async def test_unsafe_local_provider_uses_worker_process(self) -> None:
        client = _make_local_client()
        client.is_safe_for_realtime = lambda: False  # type: ignore[method-assign]

        async def fake_worker(texts: list[str], *, kind: str):
            self.assertEqual(kind, "document")
            return [[0.5] * client.dim for _ in texts]

        client._embed_local_texts_with_worker = fake_worker  # type: ignore[attr-defined, method-assign]
        with patch.object(client, "_embed_local_texts_sync", side_effect=AssertionError("must not embed in API process")):
            vectors = await client.embed_texts(["worker query"])

        self.assertEqual(vectors, [[0.5] * client.dim])

    async def test_worker_payload_includes_query_kind(self) -> None:
        client = _make_local_client()
        client.is_safe_for_realtime = lambda: False  # type: ignore[method-assign]
        captured: dict[str, object] = {}

        async def fake_worker(texts: list[str], *, kind: str):
            captured["texts"] = texts
            captured["kind"] = kind
            return [[0.5] * client.dim for _ in texts]

        client._embed_local_texts_with_worker = fake_worker  # type: ignore[attr-defined, method-assign]
        vector = await client.embed_query("worker query")

        self.assertEqual(vector, [0.5] * client.dim)
        self.assertEqual(captured, {"texts": ["worker query"], "kind": "query"})

    def test_local_worker_uses_kind_specific_encoding(self) -> None:
        fake_module = textwrap.dedent(
            """
            class BGEM3FlagModel:
                def __init__(self, *args, **kwargs):
                    pass

                def encode_queries(self, texts, **kwargs):
                    return {"dense_vecs": [[1.0] * 1024]}

                def encode(self, texts, **kwargs):
                    if isinstance(texts, str):
                        texts = [texts]
                    return {"dense_vecs": [[float(kwargs.get("max_length", 0))] * 1024 for _ in texts]}
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "FlagEmbedding.py"), "w", encoding="utf-8") as handle:
                handle.write(fake_module)
            env = os.environ.copy()
            env["PYTHONPATH"] = tmpdir + os.pathsep + env.get("PYTHONPATH", "")
            env["EMBEDDING_DIM"] = "1024"
            env["LOCAL_EMBEDDING_QUERY_MAX_LENGTH"] = "11"
            env["LOCAL_EMBEDDING_DOCUMENT_MAX_LENGTH"] = "77"
            process = subprocess.Popen(
                [sys.executable, "-m", "app.services.local_embedding_worker"],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(json.dumps({"kind": "query", "texts": ["查询"]}) + "\n")
                process.stdin.write(json.dumps({"kind": "document", "texts": ["文档"]}) + "\n")
                process.stdin.flush()
                query_response = json.loads(process.stdout.readline())
                document_response = json.loads(process.stdout.readline())
            finally:
                process.kill()
                process.wait(timeout=5)

        self.assertTrue(query_response["ok"])
        self.assertTrue(document_response["ok"])
        self.assertEqual(query_response["vectors"][0][0], 1.0)
        self.assertEqual(document_response["vectors"][0][0], 77.0)

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
        original_index_version = milvus_service.embedding_client.index_version
        milvus_service.embedding_client.provider = "local"
        milvus_service.embedding_client.model = "BAAI/bge-m3"
        milvus_service.embedding_client.dim = 1024
        milvus_service.embedding_client.index_version = "rag-layered-v1"
        try:
            store = MilvusVectorStore()
            store.enabled = True
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
            milvus_service.embedding_client.index_version = original_index_version

        self.assertIn('embedding_key == "local:BAAI/bge-m3:1024:rag-layered-v1"', str(captured["filter_expr"]))


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


class VectorIndexEmbeddingPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_index_uses_document_embedding_path(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_ensure = vector_index_service.milvus_store.ensure_knowledge_collection
        original_upsert = vector_index_service.milvus_store.upsert_knowledge_chunks
        original_embed_documents = vector_index_service.embedding_client.embed_documents
        original_embed_texts = vector_index_service.embedding_client.embed_texts

        async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
            return [[0.1] * vector_index_service.embedding_client.dim for _ in texts]

        async def fail_embed_texts(texts: list[str]) -> list[list[float]]:
            raise AssertionError("indexing must use embed_documents")

        vector_index_service.milvus_store.ensure_knowledge_collection = lambda: True
        vector_index_service.milvus_store.upsert_knowledge_chunks = lambda rows: True
        vector_index_service.embedding_client.embed_documents = fake_embed_documents
        vector_index_service.embedding_client.embed_texts = fail_embed_texts
        try:
            with Session() as db:
                article = KnowledgeArticle(
                    slug="test",
                    title="测试",
                    category="stress",
                    audience="all",
                    summary_30s="summary",
                    explanation_3min="explanation",
                    status="published",
                    review_status="published",
                )
                db.add(article)
                db.flush()
                db.add(KnowledgeChunk(article_id=article.id, chunk_index=0, title="测试", content="文档片段"))
                db.commit()

                counts = await vector_index_service.index_knowledge_chunks(db)
        finally:
            vector_index_service.milvus_store.ensure_knowledge_collection = original_ensure
            vector_index_service.milvus_store.upsert_knowledge_chunks = original_upsert
            vector_index_service.embedding_client.embed_documents = original_embed_documents
            vector_index_service.embedding_client.embed_texts = original_embed_texts

        self.assertEqual(counts.indexed, 1)

    async def test_counseling_index_uses_document_embedding_path(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        original_ensure = vector_index_service.milvus_store.ensure_counseling_collection
        original_upsert = vector_index_service.milvus_store.upsert_counseling_examples
        original_embed_documents = vector_index_service.embedding_client.embed_documents
        original_embed_texts = vector_index_service.embedding_client.embed_texts

        async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
            return [[0.1] * vector_index_service.embedding_client.dim for _ in texts]

        async def fail_embed_texts(texts: list[str]) -> list[list[float]]:
            raise AssertionError("indexing must use embed_documents")

        vector_index_service.milvus_store.ensure_counseling_collection = lambda: True
        vector_index_service.milvus_store.upsert_counseling_examples = lambda rows: True
        vector_index_service.embedding_client.embed_documents = fake_embed_documents
        vector_index_service.embedding_client.embed_texts = fail_embed_texts
        try:
            with Session() as db:
                source = CounselingCorpusSource(
                    source_key="smilechat",
                    name="SMILECHAT",
                    base_url="https://example.test",
                    license="CC0-1.0",
                    is_commercial_allowed=True,
                )
                db.add(source)
                db.flush()
                db.add(
                    CounselingExampleChunk(
                        source_id=source.id,
                        external_id="case-1",
                        chunk_index=0,
                        mode="soothe",
                        user_text="我很焦虑",
                        assistant_text="先慢一点。",
                        content="用户：我很焦虑\n咨询回应：先慢一点。",
                        status="published",
                    )
                )
                db.commit()

                counts = await vector_index_service.index_counseling_chunks(db)
        finally:
            vector_index_service.milvus_store.ensure_counseling_collection = original_ensure
            vector_index_service.milvus_store.upsert_counseling_examples = original_upsert
            vector_index_service.embedding_client.embed_documents = original_embed_documents
            vector_index_service.embedding_client.embed_texts = original_embed_texts

        self.assertEqual(counts.indexed, 1)
