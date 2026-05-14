from __future__ import annotations

import asyncio
import unittest

from app.graphs.state import AgentState
from app.services import counseling_vector_service
from app.services.counseling_chunking import DialoguePair, build_layered_chunks
from app.services.counseling_vector_service import counseling_chunk_to_vector_row
from app.services.milvus_service import MilvusVectorStore, VectorHit
from scripts import import_counseling_corpus
from scripts import index_counseling_corpus_direct


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
    meta = {
        "chunk_type": "process_segment",
        "original_external_id": "dialog-original",
        "phase": "exploration",
        "display_text": "阶段：exploration\n用户情绪线索：hurt",
        "process_quality_score": 0.76,
    }
    tags = ["vent", "关系"]


class CounselingMilvusPlanTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _hit(item_id: str, *, chunk_type: str, original_external_id: str, score: float = 0.9) -> VectorHit:
        return VectorHit(
            id=item_id,
            score=score,
            entity={
                "content": f"片段类型：{chunk_type}\n用户：我最近压力很大\n咨询回应：先慢一点。",
                "display_text": f"{chunk_type} display",
                "source_key": "smilechat",
                "source_name": "SMILECHAT",
                "mode": "soothe",
                "status": "published",
                "review_status": "approved",
                "risk_allowed": "non_crisis",
                "language": "zh-CN",
                "chunk_id": item_id,
                "chunk_type": chunk_type,
                "original_external_id": original_external_id,
            },
        )

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

    async def test_retrieval_trace_includes_embedding_and_milvus_timings(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled

        async def fake_embed_query(text: str):
            await asyncio.sleep(0)
            return [0.1] * counseling_vector_service.milvus_store.dim

        hit = VectorHit(
            id="chunk-trace",
            score=0.9,
            entity={
                "content": "用户：我最近压力很大\n咨询回应：先把压力放慢一点看。",
                "source_key": "smilechat",
                "source_name": "SMILECHAT",
                "mode": "soothe",
                "status": "published",
                "review_status": "approved",
                "risk_allowed": "non_crisis",
                "language": "zh-CN",
                "chunk_id": "chunk-trace",
                "chunk_type": "process_segment",
                "original_external_id": "case-trace",
                "phase": "exploration",
                "display_text": "阶段：exploration\n用户情绪线索：anxiety",
                "process_quality_score": "0.82",
            },
        )

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: [hit]
        object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", True)
        try:
            state = AgentState(
                normalized_text="我最近压力很大，晚上睡不着",
                risk_level="L0",
                route_priority="P2_support",
                control_category="normal_support",
            )
            result = await counseling_vector_service.retrieve_counseling_examples_with_trace(
                state,
                mode="soothe",
                limit=3,
            )
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.milvus_store.__class__.is_available = original_is_available
            counseling_vector_service.embedding_client.embed_query = original_embed_query
            counseling_vector_service.milvus_store.search_counseling_examples = original_search
            object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", original_rag_enabled)

        self.assertEqual(len(result.examples), 1)
        self.assertEqual(result.trace["status"], "hit")
        self.assertEqual(result.trace["hit_count"], 1)
        self.assertIn("embedding_duration_ms", result.trace)
        self.assertIn("milvus_duration_ms", result.trace)
        self.assertIn("total_duration_ms", result.trace)
        self.assertEqual(result.examples[0].chunk_type, "process_segment")
        self.assertEqual(result.examples[0].original_external_id, "case-trace")
        self.assertEqual(result.examples[0].phase, "exploration")
        self.assertEqual(result.examples[0].display_text, "阶段：exploration\n用户情绪线索：anxiety")
        self.assertEqual(result.examples[0].process_quality_score, 0.82)

    def test_milvus_disabled_returns_no_hits(self) -> None:
        store = MilvusVectorStore()
        store.enabled = False

        self.assertFalse(store.ensure_collections())
        self.assertEqual(store.search_knowledge([0.1] * store.dim), [])
        self.assertEqual(store.search_counseling_examples([0.1] * store.dim), [])

    def test_companion_retrieval_tries_broad_search_first(self) -> None:
        self.assertIsNone(counseling_vector_service._search_modes_for("companion")[0])

    async def test_retrieval_uses_default_chunk_type_quotas(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("session-1", chunk_type="session_sketch", original_external_id="case-1", score=0.99),
            self._hit("process-1", chunk_type="process_segment", original_external_id="case-2", score=0.95),
            self._hit("turn-1", chunk_type="turn_pair", original_external_id="case-3", score=0.9),
            self._hit("turn-2", chunk_type="turn_pair", original_external_id="case-4", score=0.89),
        ]

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", True)
        try:
            state = AgentState(
                normalized_text="我最近压力很大，睡不好",
                risk_level="L0",
                route_priority="P2_support",
                control_category="normal_support",
            )
            result = await counseling_vector_service.retrieve_counseling_examples_with_trace(state, mode="soothe", limit=3)
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.milvus_store.__class__.is_available = original_is_available
            counseling_vector_service.embedding_client.embed_query = original_embed_query
            counseling_vector_service.milvus_store.search_counseling_examples = original_search
            object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", original_rag_enabled)

        self.assertEqual([example.chunk_type for example in result.examples], ["process_segment", "turn_pair", "turn_pair"])
        self.assertEqual(result.trace["chunk_type_counts"], {"process_segment": 1, "turn_pair": 2})

    async def test_retrieval_allows_session_sketch_for_continuation_turns(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("session-1", chunk_type="session_sketch", original_external_id="case-1", score=0.99),
            self._hit("process-1", chunk_type="process_segment", original_external_id="case-2", score=0.95),
            self._hit("turn-1", chunk_type="turn_pair", original_external_id="case-3", score=0.9),
        ]

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", True)
        try:
            state = AgentState(
                normalized_text="继续刚才那个工作压力的问题",
                risk_level="L0",
                route_priority="P2_support",
                control_category="normal_support",
            )
            result = await counseling_vector_service.retrieve_counseling_examples_with_trace(state, mode="counseling", limit=3)
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.milvus_store.__class__.is_available = original_is_available
            counseling_vector_service.embedding_client.embed_query = original_embed_query
            counseling_vector_service.milvus_store.search_counseling_examples = original_search
            object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", original_rag_enabled)

        self.assertEqual([example.chunk_type for example in result.examples], ["session_sketch", "process_segment", "turn_pair"])

    def test_counseling_vector_row_keeps_source_metadata(self) -> None:
        row = counseling_chunk_to_vector_row(FakeChunk(), FakeSource(), [0.1, 0.2])

        self.assertEqual(row["id"], "chunk-1")
        self.assertEqual(row["source_key"], "smilechat")
        self.assertEqual(row["source_name"], "SMILECHAT")
        self.assertEqual(row["license"], "CC0-1.0")
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["embedding_key"], counseling_vector_service.embedding_client.embedding_key)
        self.assertEqual(row["chunk_type"], "process_segment")
        self.assertEqual(row["original_external_id"], "dialog-original")
        self.assertEqual(row["phase"], "exploration")
        self.assertEqual(row["display_text"], "阶段：exploration\n用户情绪线索：hurt")
        self.assertEqual(row["process_quality_score"], "0.76")

    def test_counseling_search_requests_layered_metadata_fields(self) -> None:
        store = MilvusVectorStore()
        store.enabled = True
        captured: dict[str, object] = {}

        def fake_search_rest(*args: object, **kwargs: object) -> list[VectorHit]:
            captured.update(kwargs)
            return []

        store._search_rest = fake_search_rest  # type: ignore[method-assign]
        store.search_counseling_examples([0.1] * store.dim)

        output_fields = captured["output_fields"]
        self.assertIn("chunk_type", output_fields)
        self.assertIn("original_external_id", output_fields)
        self.assertIn("phase", output_fields)
        self.assertIn("display_text", output_fields)
        self.assertIn("process_quality_score", output_fields)


class CounselingCorpusImportTests(unittest.TestCase):
    def test_layered_chunking_builds_turn_segments_and_session_sketch(self) -> None:
        pairs = [
            DialoguePair(user_text="我最近压力很大，晚上睡不好", assistant_text="听起来你已经撑了很久，我们先慢一点。"),
            DialoguePair(user_text="主要是领导一直临时加活", assistant_text="你像是被不断打断，也很难有掌控感。"),
            DialoguePair(user_text="我不知道怎么拒绝", assistant_text="我们可以先把你最想守住的边界说清楚。"),
            DialoguePair(user_text="我怕他觉得我不配合", assistant_text="这个担心很真实，也可以先准备一句温和但清晰的话。"),
            DialoguePair(user_text="这样好像没那么乱了", assistant_text="能稍微清楚一点就很好，我们先保留这个小步骤。"),
        ]

        chunks = build_layered_chunks(
            pairs,
            external_id="case-1",
            topic="工作压力",
            parser="messages",
        )

        turn_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "turn_pair"]
        process_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "process_segment"]
        sketch_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "session_sketch"]

        self.assertEqual(len(turn_chunks), 5)
        self.assertGreaterEqual(len(process_chunks), 2)
        self.assertEqual(len(sketch_chunks), 1)
        self.assertEqual(process_chunks[0].metadata["pair_end"], process_chunks[1].metadata["pair_start"])
        self.assertEqual(process_chunks[0].metadata["overlap_pairs"], 1)
        self.assertIn("片段类型：整段咨询地图", sketch_chunks[0].content)
        self.assertNotIn("领导一直临时加活", sketch_chunks[0].metadata["display_text"])

    def test_layered_chunking_skips_all_chunks_for_unsafe_pair(self) -> None:
        pairs = [
            DialoguePair(user_text="我今晚想自杀", assistant_text="我听到了你的痛苦。"),
            DialoguePair(user_text="我不知道怎么办", assistant_text="我们先联系身边可信任的人。"),
        ]

        chunks = build_layered_chunks(
            pairs,
            external_id="case-risk",
            topic="危机",
            parser="messages",
        )

        self.assertEqual(chunks, [])

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

    def test_parser_builds_layered_chunks_for_multi_turn_dialogue(self) -> None:
        item = {
            "id": "case-layered",
            "normalizedTag": "工作压力",
            "messages": [
                {"role": "user", "content": "我最近压力很大，晚上睡不好"},
                {"role": "assistant", "content": "听起来你已经撑了很久，我们先慢一点。"},
                {"role": "user", "content": "主要是领导一直临时加活"},
                {"role": "assistant", "content": "你像是被不断打断，也很难有掌控感。"},
                {"role": "user", "content": "我不知道怎么拒绝"},
                {"role": "assistant", "content": "我们可以先把你最想守住的边界说清楚。"},
            ],
        }

        parsed = import_counseling_corpus._parse_item(item, 0, source_key="smilechat")
        chunk_types = [example.metadata["chunk_type"] for example in parsed]

        self.assertEqual(chunk_types.count("turn_pair"), 3)
        self.assertEqual(chunk_types.count("process_segment"), 1)
        self.assertEqual(chunk_types.count("session_sketch"), 1)
        self.assertEqual(parsed[0].external_id, "smilechat_case-layered::turn")
        self.assertEqual(parsed[0].metadata["original_external_id"], "smilechat_case-layered")
        self.assertIn("display_text", parsed[-1].metadata)
        self.assertNotIn("领导一直临时加活", parsed[-1].metadata["display_text"])

    def test_direct_index_parser_uses_layered_chunks(self) -> None:
        item = {
            "id": "case-direct",
            "normalizedTag": "工作压力",
            "messages": [
                {"role": "user", "content": "我最近压力很大，晚上睡不好"},
                {"role": "assistant", "content": "听起来你已经撑了很久，我们先慢一点。"},
                {"role": "user", "content": "主要是领导一直临时加活"},
                {"role": "assistant", "content": "你像是被不断打断，也很难有掌控感。"},
                {"role": "user", "content": "我不知道怎么拒绝"},
                {"role": "assistant", "content": "我们可以先把你最想守住的边界说清楚。"},
            ],
        }

        parsed = list(index_counseling_corpus_direct._parse_item(item, 0, "smilechat"))
        chunk_types = [example.metadata["chunk_type"] for example in parsed]

        self.assertEqual(chunk_types.count("turn_pair"), 3)
        self.assertEqual(chunk_types.count("process_segment"), 1)
        self.assertEqual(chunk_types.count("session_sketch"), 1)
        self.assertEqual(parsed[0].external_id, "smilechat_case-direct::turn")
        self.assertEqual(parsed[0].metadata["original_external_id"], "smilechat_case-direct")
        self.assertIn("display_text", parsed[-1].metadata)

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
