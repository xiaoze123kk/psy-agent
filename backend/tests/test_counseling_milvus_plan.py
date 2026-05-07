from __future__ import annotations

import unittest

from app.graphs.state import AgentState
from app.services import counseling_vector_service
from app.services.counseling_vector_service import counseling_chunk_to_vector_row
from app.services.milvus_service import MilvusVectorStore
from scripts import import_counseling_corpus


class FakeSource:
    id = "source-1"
    source_key = "smilechat"
    name = "SMILECHAT"
    base_url = "https://github.com/qiuhuachuan/smile"
    license = "CC0-1.0"


class FakeChunk:
    id = "chunk-1"
    external_id = "dialog-1"
    mode = "vent"
    topic = "关系"
    source_url = None
    license = None
    status = "published"
    content = "用户：我觉得没人理解我\n咨询回应：这听起来很孤单。"


class CounselingMilvusPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_risk_state_does_not_call_embedding(self) -> None:
        original_embed_query = counseling_vector_service.embedding_client.embed_query

        async def fail_if_called(text: str):
            raise AssertionError("high-risk counseling turns must not call embedding retrieval")

        counseling_vector_service.embedding_client.embed_query = fail_if_called
        try:
            state = AgentState(normalized_text="我想伤害自己", risk_level="L2")
            hits = await counseling_vector_service.retrieve_counseling_examples(state, mode="vent")
        finally:
            counseling_vector_service.embedding_client.embed_query = original_embed_query

        self.assertEqual(hits, [])

    async def test_disabled_milvus_does_not_call_embedding(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_embed_query = counseling_vector_service.embedding_client.embed_query

        async def fail_if_called(text: str):
            raise AssertionError("disabled Milvus must not call embedding retrieval")

        counseling_vector_service.milvus_store.enabled = False
        counseling_vector_service.embedding_client.embed_query = fail_if_called
        try:
            state = AgentState(normalized_text="我最近总是焦虑", risk_level="L0")
            hits = await counseling_vector_service.retrieve_counseling_examples(state, mode="soothe")
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.embedding_client.embed_query = original_embed_query

        self.assertEqual(hits, [])

    def test_milvus_disabled_returns_no_hits(self) -> None:
        store = MilvusVectorStore()
        store.enabled = False

        self.assertFalse(store.ensure_collections())
        self.assertEqual(store.search_knowledge([0.1] * store.dim), [])
        self.assertEqual(store.search_counseling_examples([0.1] * store.dim), [])

    def test_counseling_vector_row_keeps_source_metadata(self) -> None:
        row = counseling_chunk_to_vector_row(FakeChunk(), FakeSource(), [0.1, 0.2])

        self.assertEqual(row["id"], "chunk-1")
        self.assertEqual(row["source_key"], "smilechat")
        self.assertEqual(row["source_name"], "SMILECHAT")
        self.assertEqual(row["license"], "CC0-1.0")
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["embedding_key"], counseling_vector_service.embedding_client.embedding_key)


class CounselingCorpusImportTests(unittest.TestCase):
    def test_parser_desensitizes_and_classifies_chinese_dialogue(self) -> None:
        item = {
            "id": "case-1",
            "normalizedTag": "关系",
            "messages": [
                {"role": "user", "content": "我觉得没人理解我，手机号13812345678"},
                {"role": "assistant", "content": "被这样忽视的时候，确实会很孤单。你愿意多说一点发生了什么吗？"},
            ],
        }

        parsed = import_counseling_corpus._parse_item(item, 0)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].mode, "vent")
        self.assertIn("[手机号]", parsed[0].user_text)
        self.assertIn("SMILECHAT", counseling_vector_service.COUNSELING_CORPUS_SOURCES["smilechat"]["name"])

    def test_parser_filters_high_risk_examples(self) -> None:
        item = {
            "id": "case-2",
            "messages": [
                {"role": "user", "content": "我今晚想自杀"},
                {"role": "assistant", "content": "我听到了你的痛苦。"},
            ],
        }

        self.assertEqual(import_counseling_corpus._parse_item(item, 0), [])


if __name__ == "__main__":
    unittest.main()
