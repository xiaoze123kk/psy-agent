from __future__ import annotations

import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    ConversationThread,
    MemoryConsolidationRun,
    MemoryOperation,
    MoodLog,
    User,
    UserMemory,
    UserProfile,
    UserSettings,
    utcnow,
)
from app.services.memory_service import (
    build_memory_index,
    consolidate_user_memories,
    index_memory_embeddings,
    maybe_auto_consolidate_user_memories,
    retrieve_memories_for_turn,
    upsert_memory_candidates,
)
from app.services import memory_service


class FakeMemoryVectorStore:
    is_enabled = True
    is_available = True

    def __init__(self, hits_by_vector: dict[tuple[float, ...], list[tuple[str, float]]]) -> None:
        self.hits_by_vector = hits_by_vector
        self.calls: list[dict[str, object]] = []

    def search_user_memories(self, vector: list[float], **kwargs):
        self.calls.append({"vector": vector, **kwargs})
        key = tuple(round(float(value), 3) for value in vector)
        return [
            SimpleNamespace(id=memory_id, score=score, entity={"memory_id": memory_id})
            for memory_id, score in self.hits_by_vector.get(key, [])
        ]


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, class_=Session)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo", *, memory_mode: str = "long_term") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname=username,
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode=memory_mode,
                    companion_style="gentle",
                    voice_enabled=False,
                    save_voice_audio=False,
                    save_transcript=True,
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_thread(self, user: User, suffix: str = "main") -> ConversationThread:
        thread = ConversationThread(
            user_id=user.id,
            langgraph_thread_id=f"lg-{user.username}-{suffix}",
            title=f"session {suffix}",
        )
        self.db.add(thread)
        self.db.commit()
        self.db.refresh(thread)
        return thread

    def add_memory(
        self,
        user: User,
        *,
        memory_type: str,
        content: str,
        importance: int = 3,
        visibility: str = "user_visible",
        status: str = "active",
        review_state: str = "normal",
        expires_at=None,
    ) -> UserMemory:
        memory = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            title=f"{memory_type}: {content[:32]}",
            summary=content,
            content=content,
            tags=[],
            importance=importance,
            visibility=visibility,
            status=status,
            review_state=review_state,
            expires_at=expires_at,
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def add_threads(self, user: User, count: int) -> None:
        for index in range(count):
            self.db.add(
                ConversationThread(
                    user_id=user.id,
                    langgraph_thread_id=f"lg-{user.username}-{index}",
                    title=f"session {index}",
                    updated_at=utcnow(),
                )
            )
        self.db.commit()

    def test_retrieve_records_specific_hit_access_and_audit(self) -> None:
        user = self.create_user(memory_mode="long_term")
        target = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="exam anxiety before finals",
            importance=2,
        )
        self.add_memory(user, memory_type="preference", content="favorite drink is tea", importance=5)

        results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="exam anxiety again",
            memory_mode="long_term",
            limit=5,
        )
        self.db.commit()
        self.db.refresh(target)

        hit = next(item for item in results if item["memory_id"] == target.id)
        self.assertGreater(hit["score"], 0)
        self.assertTrue(hit["why_selected"])
        self.assertEqual(target.access_count, 1)
        self.assertIsNotNone(target.last_accessed_at)
        retrieve_operation = self.db.scalar(
            select(MemoryOperation).where(MemoryOperation.user_id == user.id, MemoryOperation.action == "retrieve")
        )
        self.assertIsNotNone(retrieve_operation)
        self.assertIn(target.id, retrieve_operation.after_value["memory_ids"])

    def test_retrieve_prefers_relevance_and_excludes_inactive_memories(self) -> None:
        user = self.create_user(memory_mode="long_term")
        target = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="exam anxiety before finals",
            importance=1,
        )
        self.add_memory(user, memory_type="preference", content="favorite breakfast oatmeal", importance=5)
        deleted = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="deleted exam anxiety",
            status="deleted",
        )
        expired = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="expired exam anxiety",
            expires_at=utcnow() - timedelta(days=1),
        )
        do_not_use = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="do not use exam anxiety",
            review_state="do_not_use",
        )

        results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="exam anxiety before finals",
            memory_mode="long_term",
            limit=5,
        )

        result_ids = [item["memory_id"] for item in results]
        self.assertEqual(result_ids[0], target.id)
        self.assertNotIn(deleted.id, result_ids)
        self.assertNotIn(expired.id, result_ids)
        self.assertNotIn(do_not_use.id, result_ids)

    def test_memory_modes_and_high_risk_internal_safety_filtering(self) -> None:
        user = self.create_user(memory_mode="summary_only")
        summary = self.add_memory(user, memory_type="session_summary", content="last session about exam stress")
        preference = self.add_memory(user, memory_type="preference", content="prefers reassurance first")

        summary_only = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="reassurance first",
            memory_mode="summary_only",
            limit=5,
        )
        off_results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="exam stress",
            memory_mode="off",
            limit=5,
        )

        safety = self.add_memory(
            user,
            memory_type="safety_summary",
            content="internal safety summary",
            visibility="internal_safety",
        )
        high_risk_results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="crisis",
            memory_mode="long_term",
            risk_level="L2",
            limit=5,
        )
        high_risk_index = build_memory_index(
            self.db,
            user.id,
            memory_mode="long_term",
            include_internal=True,
        )

        self.assertEqual([item["memory_id"] for item in summary_only], [summary.id])
        self.assertNotIn(preference.id, [item["memory_id"] for item in summary_only])
        self.assertEqual(off_results, [])
        self.assertEqual([item["memory_id"] for item in high_risk_results], [safety.id])
        self.assertEqual([item["memory_id"] for item in high_risk_index], [safety.id])

    def test_summary_only_build_memory_index_respects_memory_types_before_limit(self) -> None:
        user = self.create_user(memory_mode="summary_only")
        for index in range(200):
            self.add_memory(
                user,
                memory_type="preference",
                content=f"preference memory {index}",
                importance=5,
            )
        summary = self.add_memory(
            user,
            memory_type="session_summary",
            content="last session summary about exam stress",
            importance=1,
        )

        results = build_memory_index(
            self.db,
            user.id,
            memory_mode="summary_only",
        )

        self.assertEqual([item["memory_id"] for item in results], [summary.id])

    def test_summary_only_retrieve_memories_respects_memory_types_before_limit(self) -> None:
        user = self.create_user(memory_mode="summary_only")
        for index in range(200):
            self.add_memory(
                user,
                memory_type="preference",
                content=f"preference memory {index}",
                importance=5,
            )
        summary = self.add_memory(
            user,
            memory_type="session_summary",
            content="last session summary about exam stress",
            importance=1,
        )

        results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="exam stress",
            memory_mode="summary_only",
            limit=5,
        )

        self.assertEqual([item["memory_id"] for item in results], [summary.id])

    def test_vector_hits_are_merged_into_hybrid_retrieval(self) -> None:
        user = self.create_user(memory_mode="long_term")
        target = self.add_memory(
            user,
            memory_type="support_strategy",
            content="box breathing with feet on the floor helps",
            importance=1,
        )
        self.add_memory(user, memory_type="preference", content="unrelated favorite tea", importance=5)
        fake_store = FakeMemoryVectorStore({(0.9, 0.1): [(target.id, 0.97)]})
        original_store = memory_service.milvus_store
        original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "1"
        memory_service.milvus_store = fake_store
        try:
            results = retrieve_memories_for_turn(
                self.db,
                user_id=user.id,
                query="please help me stabilize",
                memory_mode="long_term",
                limit=5,
                query_vector=[0.9, 0.1],
            )
        finally:
            memory_service.milvus_store = original_store
            if original_vector_retrieval is None:
                os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
            else:
                os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = original_vector_retrieval

        self.assertEqual(results[0]["memory_id"], target.id)
        self.assertEqual(results[0]["why_selected"], "vector_semantic_match")
        self.assertEqual(fake_store.calls[0]["user_id"], user.id)
        self.assertIn("support_strategy", fake_store.calls[0]["memory_types"])

    def test_index_memory_embeddings_loads_existing_rows_once_for_multiple_memories(self) -> None:
        user = self.create_user(memory_mode="long_term")
        first = self.add_memory(user, memory_type="preference", content="prefers grounding before advice")
        second = self.add_memory(user, memory_type="support_strategy", content="box breathing helps when anxious")
        existing = memory_service.MemoryEmbedding(
            memory_id=first.id,
            user_id=user.id,
            embedding=[0.1, 0.2],
            embedding_model="test-model",
            embedding_key="test:embedding:2",
            content_hash="old-hash",
        )
        self.db.add(existing)
        self.db.commit()

        original_env = os.environ.get("MEMORY_EMBEDDINGS_ENABLED")
        os.environ["MEMORY_EMBEDDINGS_ENABLED"] = "1"
        original_client = memory_service.embedding_client

        class FakeEmbeddingClient:
            is_configured = True
            model = "test-model"
            embedding_key = "test:embedding:2"

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[float(index + 1), float(index + 2)] for index, _ in enumerate(texts)]

        fake_client = FakeEmbeddingClient()
        memory_service.embedding_client = fake_client
        original_store = memory_service.milvus_store

        class FakeMilvusStore:
            is_enabled = True

            def upsert_memory_vectors(self, rows):
                self.rows = rows

        memory_service.milvus_store = FakeMilvusStore()
        select_count = 0

        def count_memory_embedding_selects(conn, cursor, statement, parameters, context, executemany):
            nonlocal select_count
            normalized = statement.lower()
            if "select" in normalized and "from memory_embeddings" in normalized:
                select_count += 1

        event.listen(self.engine, "before_cursor_execute", count_memory_embedding_selects)
        try:
            import asyncio

            asyncio.run(index_memory_embeddings(self.db, [first, second]))
            self.db.commit()
        finally:
            event.remove(self.engine, "before_cursor_execute", count_memory_embedding_selects)
            memory_service.embedding_client = original_client
            memory_service.milvus_store = original_store
            if original_env is None:
                os.environ.pop("MEMORY_EMBEDDINGS_ENABLED", None)
            else:
                os.environ["MEMORY_EMBEDDINGS_ENABLED"] = original_env

        embeddings = list(
            self.db.scalars(
                select(memory_service.MemoryEmbedding)
                .where(memory_service.MemoryEmbedding.user_id == user.id)
                .order_by(memory_service.MemoryEmbedding.memory_id)
            )
        )
        self.db.refresh(existing)
        embeddings_by_memory_id = {row.memory_id: row for row in embeddings}

        self.assertEqual(select_count, 1)
        self.assertEqual(len(embeddings), 2)
        self.assertEqual(embeddings_by_memory_id[first.id].embedding, [1.0, 2.0])
        self.assertEqual(embeddings_by_memory_id[first.id].embedding_model, "test-model")
        self.assertEqual(embeddings_by_memory_id[first.id].embedding_key, "test:embedding:2")
        self.assertEqual(embeddings_by_memory_id[second.id].embedding, [2.0, 3.0])
        self.assertEqual(existing.embedding, [1.0, 2.0])

    def test_vector_retrieval_recall_and_precision_metrics(self) -> None:
        user = self.create_user(memory_mode="long_term")
        trigger = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="final exam season tends to trigger panic",
            importance=1,
        )
        strategy = self.add_memory(
            user,
            memory_type="support_strategy",
            content="slow grounding exercise helps after conflict",
            importance=1,
        )
        relationship = self.add_memory(
            user,
            memory_type="relationship",
            content="conflict with mother is a recurring relationship theme",
            importance=1,
        )
        decoy = self.add_memory(user, memory_type="profile", content="likes quiet mornings", importance=5)
        fake_store = FakeMemoryVectorStore(
            {
                (1.0, 0.0, 0.0): [(trigger.id, 0.98), (decoy.id, 0.2)],
                (0.0, 1.0, 0.0): [(strategy.id, 0.98), (decoy.id, 0.2)],
                (0.0, 0.0, 1.0): [(relationship.id, 0.98), (decoy.id, 0.2)],
            }
        )
        cases = [
            ("I am scared of finals again", [1.0, 0.0, 0.0], trigger.id),
            ("help me ground after the argument", [0.0, 1.0, 0.0], strategy.id),
            ("my mom and I had the same fight", [0.0, 0.0, 1.0], relationship.id),
        ]
        original_store = memory_service.milvus_store
        original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "1"
        memory_service.milvus_store = fake_store
        try:
            top5_hits = 0
            top1_hits = 0
            for query, vector, expected_id in cases:
                results = retrieve_memories_for_turn(
                    self.db,
                    user_id=user.id,
                    query=query,
                    memory_mode="long_term",
                    limit=5,
                    record_access=False,
                    query_vector=vector,
                )
                result_ids = [item["memory_id"] for item in results]
                top5_hits += int(expected_id in result_ids[:5])
                top1_hits += int(bool(result_ids) and result_ids[0] == expected_id)
        finally:
            memory_service.milvus_store = original_store
            if original_vector_retrieval is None:
                os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
            else:
                os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = original_vector_retrieval

        recall_at_5 = top5_hits / len(cases)
        precision_at_1 = top1_hits / len(cases)
        self.assertGreaterEqual(recall_at_5, 1.0)
        self.assertGreaterEqual(precision_at_1, 1.0)

    def test_upsert_merges_duplicates_and_records_metadata(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)
        assistant_result = {
            "should_write_memory": True,
            "risk_level": "L0",
            "memory_candidates": [
                {
                    "memory_type": "preference",
                    "content": "prefers grounding before advice",
                    "importance": 4,
                    "tags": ["grounding"],
                    "structured_value": {"basis": "explicit_user_statement"},
                }
            ],
        }

        written, decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000001",
            assistant_result=assistant_result,
        )
        second_written, second_decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000002",
            assistant_result=assistant_result,
        )
        self.db.commit()
        memory = written[0]
        self.db.refresh(memory)
        operations = list(
            self.db.scalars(
                select(MemoryOperation)
                .where(MemoryOperation.user_id == user.id)
                .order_by(MemoryOperation.created_at)
            )
        )

        self.assertEqual(decisions[0]["status"], "created")
        self.assertEqual(second_decisions[0]["status"], "updated")
        self.assertEqual(second_written[0].id, memory.id)
        self.assertEqual(memory.memory_type, "preference")
        self.assertTrue(memory.title)
        self.assertTrue(memory.summary)
        self.assertIn("grounding", memory.tags)
        self.assertEqual(memory.structured_value["thread_id"], thread.id)
        self.assertEqual(memory.structured_value["risk_level"], "L0")
        self.assertEqual(memory.structured_value["basis"], "explicit_user_statement")
        self.assertEqual(memory.version, 2)
        self.assertEqual([operation.action for operation in operations], ["create", "update"])

    def test_upsert_blocks_sensitive_visible_and_allows_high_risk_safety_summary(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)

        _, blocked_decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000003",
            assistant_result={
                "should_write_memory": True,
                "risk_level": "L0",
                "memory_candidates": [
                    {
                        "memory_type": "profile",
                        "content": "ptsd diagnosis detail should not become visible memory",
                        "importance": 4,
                    }
                ],
            },
        )
        written, safety_decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000004",
            assistant_result={
                "should_write_memory": True,
                "risk_level": "L2",
                "memory_candidates": [
                    {"memory_type": "safety_summary", "content": "L2 safety summary", "importance": 5}
                ],
            },
        )
        self.db.commit()
        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))

        self.assertEqual(blocked_decisions[0]["status"], "blocked")
        self.assertIn("contains_sensitive_term", blocked_decisions[0]["reason"])
        self.assertEqual(safety_decisions[0]["status"], "created")
        self.assertEqual(len(memories), 1)
        self.assertEqual(written[0].memory_type, "safety_summary")
        self.assertEqual(written[0].visibility, "internal_safety")

    def test_upsert_ignores_expired_memory_when_finding_similar_match(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)
        expired = self.add_memory(
            user,
            memory_type="preference",
            content="prefers reassurance before advice",
            importance=5,
            expires_at=utcnow() - timedelta(days=1),
        )
        decoy = self.add_memory(
            user,
            memory_type="preference",
            content="enjoys tea and quiet mornings",
            importance=1,
        )

        written, decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000101",
            assistant_result={
                "should_write_memory": True,
                "risk_level": "L0",
                "memory_candidates": [
                    {
                        "memory_type": "preference",
                        "content": "prefers reassurance before advice",
                        "importance": 5,
                    }
                ],
                "session_summary": "prefers reassurance before advice",
                "memory_policy": "write_safe_summary",
            },
        )
        self.db.commit()
        self.db.refresh(expired)
        self.db.refresh(decoy)

        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))

        self.assertEqual(decisions[0]["status"], "created")
        self.assertNotIn(written[0].id, {expired.id, decoy.id})
        self.assertEqual(expired.version, 1)
        self.assertEqual(decoy.version, 1)
        self.assertEqual(len(memories), 3)

    def test_upsert_ignores_do_not_use_memory_when_finding_similar_match(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)
        blocked = self.add_memory(
            user,
            memory_type="preference",
            content="prefers grounding before advice",
            importance=5,
            review_state="do_not_use",
        )
        decoy = self.add_memory(
            user,
            memory_type="preference",
            content="enjoys tea and quiet mornings",
            importance=1,
        )

        written, decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000102",
            assistant_result={
                "should_write_memory": True,
                "risk_level": "L0",
                "memory_candidates": [
                    {
                        "memory_type": "preference",
                        "content": "prefers grounding before advice",
                        "importance": 5,
                    }
                ],
                "session_summary": "prefers grounding before advice",
                "memory_policy": "write_safe_summary",
            },
        )
        self.db.commit()
        self.db.refresh(blocked)
        self.db.refresh(decoy)

        memories = list(self.db.scalars(select(UserMemory).where(UserMemory.user_id == user.id)))

        self.assertEqual(decisions[0]["status"], "created")
        self.assertNotIn(written[0].id, {blocked.id, decoy.id})
        self.assertEqual(blocked.version, 1)
        self.assertEqual(decoy.version, 1)
        self.assertEqual(len(memories), 3)

    def test_find_similar_memory_prefilter_skips_unrelated_candidates(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)
        anchor = self.add_memory(
            user,
            memory_type="preference",
            content="prefers reassurance before advice",
            importance=4,
        )
        for idx in range(24):
            self.add_memory(
                user,
                memory_type="preference",
                content=f"completely unrelated note about tea and weather {idx}",
                importance=5,
            )

        similarity_calls = 0
        original_similarity = memory_service._content_similarity

        def counted_similarity(left: str, right: str) -> float:
            nonlocal similarity_calls
            similarity_calls += 1
            return original_similarity(left, right)

        with patch("app.services.memory_service._content_similarity", side_effect=counted_similarity):
            written, decisions = upsert_memory_candidates(
                self.db,
                user=user,
                thread=thread,
                assistant_message_id="00000000-0000-0000-0000-000000000103",
                assistant_result={
                    "should_write_memory": True,
                    "risk_level": "L0",
                    "memory_candidates": [
                        {
                            "memory_type": "preference",
                            "content": "prefers reassurance before advice.",
                            "importance": 4,
                        }
                    ],
                    "session_summary": "prefers reassurance before advice.",
                    "memory_policy": "write_safe_summary",
                },
            )

        self.db.refresh(anchor)

        self.assertEqual(decisions[0]["status"], "updated")
        self.assertEqual(written[0].id, anchor.id)
        self.assertLessEqual(similarity_calls, 2)
        self.assertEqual(anchor.version, 2)

    def test_find_similar_memory_prefilter_still_allows_similar_merge(self) -> None:
        user = self.create_user(memory_mode="long_term")
        thread = self.create_thread(user)
        anchor = self.add_memory(
            user,
            memory_type="preference",
            content="prefers reassurance before advice",
            importance=4,
        )
        self.add_memory(
            user,
            memory_type="preference",
            content="unrelated tea preference with no overlap",
            importance=5,
        )

        written, decisions = upsert_memory_candidates(
            self.db,
            user=user,
            thread=thread,
            assistant_message_id="00000000-0000-0000-0000-000000000104",
            assistant_result={
                "should_write_memory": True,
                "risk_level": "L0",
                "memory_candidates": [
                    {
                        "memory_type": "preference",
                        "content": "prefers reassurance before advice.",
                        "importance": 4,
                    }
                ],
                "session_summary": "prefers reassurance before advice.",
                "memory_policy": "write_safe_summary",
            },
        )
        self.db.refresh(anchor)

        self.assertEqual(decisions[0]["status"], "updated")
        self.assertEqual(written[0].id, anchor.id)
        self.assertEqual(anchor.version, 2)

    def test_consolidate_merges_expires_writes_state_and_audit(self) -> None:
        user = self.create_user(memory_mode="long_term")
        first = self.add_memory(user, memory_type="preference", content="prefers reassurance first")
        duplicate = self.add_memory(user, memory_type="preference", content="prefers reassurance first")
        expired = self.add_memory(
            user,
            memory_type="support_strategy",
            content="temporary breathing plan",
            expires_at=utcnow() - timedelta(days=1),
        )
        self.db.add_all(
            [
                MoodLog(user_id=user.id, mood_score=2, mood_tags=["anxious"], source="checkin"),
                MoodLog(user_id=user.id, mood_score=3, mood_tags=["anxious", "tired"], source="checkin"),
                MoodLog(user_id=user.id, mood_score=4, mood_tags=["tired"], source="checkin"),
            ]
        )
        self.db.commit()

        result = consolidate_user_memories(self.db, user_id=user.id, force=True)
        self.db.commit()
        self.db.refresh(first)
        self.db.refresh(duplicate)
        self.db.refresh(expired)
        state_memory = self.db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user.id,
                UserMemory.memory_type == "state",
                UserMemory.status == "active",
            )
        )
        actions = list(self.db.scalars(select(MemoryOperation.action).where(MemoryOperation.user_id == user.id)))

        self.assertEqual(result["status"], "completed")
        self.assertEqual([first.status, duplicate.status].count("deleted"), 1)
        self.assertIn(duplicate.supersedes_id or first.supersedes_id, {first.id, duplicate.id})
        self.assertEqual(expired.status, "expired")
        self.assertIsNotNone(state_memory)
        self.assertEqual(state_memory.structured_value["log_count"], 3)
        self.assertAlmostEqual(state_memory.structured_value["avg_mood_score"], 3.0)
        self.assertIn("consolidate", actions)
        self.assertIn("expire", actions)

    def test_consolidate_running_lock_returns_existing_run_unless_forced(self) -> None:
        user = self.create_user(memory_mode="long_term")
        running = MemoryConsolidationRun(
            user_id=user.id,
            status="running",
            trigger="auto",
            started_at=utcnow(),
        )
        self.db.add(running)
        self.db.commit()

        locked = consolidate_user_memories(self.db, user_id=user.id, force=False)
        forced = consolidate_user_memories(self.db, user_id=user.id, force=True)
        self.db.commit()

        self.assertEqual(locked["run_id"], running.id)
        self.assertEqual(locked["status"], "running")
        self.assertEqual(forced["status"], "completed")
        self.assertNotEqual(forced["run_id"], running.id)

    def test_maybe_auto_consolidate_gate_requires_day_and_session_count(self) -> None:
        recent = self.create_user("recent", memory_mode="long_term")
        self.add_threads(recent, 5)
        self.db.add(
            MemoryConsolidationRun(
                user_id=recent.id,
                status="completed",
                trigger="manual",
                started_at=utcnow(),
                completed_at=utcnow(),
            )
        )
        few = self.create_user("few", memory_mode="long_term")
        self.add_threads(few, 4)
        ready = self.create_user("ready", memory_mode="long_term")
        self.add_threads(ready, 5)
        self.db.commit()

        self.assertIsNone(maybe_auto_consolidate_user_memories(self.db, user_id=recent.id))
        self.assertIsNone(maybe_auto_consolidate_user_memories(self.db, user_id=few.id))
        result = maybe_auto_consolidate_user_memories(self.db, user_id=ready.id)
        self.db.commit()
        auto_run = self.db.scalar(
            select(MemoryConsolidationRun).where(
                MemoryConsolidationRun.user_id == ready.id,
                MemoryConsolidationRun.trigger == "auto",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(auto_run)
        self.assertEqual(auto_run.sessions_reviewed, 5)


if __name__ == "__main__":
    unittest.main()
