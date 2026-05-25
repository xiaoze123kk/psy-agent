from __future__ import annotations

import os
import time
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, UserMemory, UserProfile, UserSettings, utcnow
from app.services import memory_service
from app.services.embedding_service import embedding_client
from app.services.memory_service import retrieve_memories_for_turn
from app.services.milvus_service import milvus_store


@unittest.skipUnless(
    os.getenv("RUN_MILVUS_MEMORY_EVAL") == "1",
    "Set RUN_MILVUS_MEMORY_EVAL=1 with a running Milvus instance to run memory vector recall evaluation.",
)
class MilvusMemoryRecallEvalTests(unittest.TestCase):
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
        self.addCleanup(self._dispose_db)

        self.original_store_state = {
            "enabled": milvus_store.enabled,
            "dim": milvus_store.dim,
            "collection_prefix": milvus_store.collection_prefix,
            "_client": milvus_store._client,
            "_client_error": milvus_store._client_error,
            "_field_cache": dict(milvus_store._field_cache),
            "memory_service_store": memory_service.milvus_store,
        }
        self.original_embedding_state = {
            "provider": embedding_client.provider,
            "model": embedding_client.model,
            "dim": embedding_client.dim,
        }
        self.original_vector_retrieval = os.environ.get("MEMORY_VECTOR_RETRIEVAL_ENABLED")
        os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = "1"
        self.test_prefix = f"memory_eval_{uuid.uuid4().hex[:10]}"
        milvus_store.enabled = True
        milvus_store.dim = 3
        milvus_store.collection_prefix = self.test_prefix
        milvus_store._client = None
        milvus_store._client_error = None
        milvus_store._field_cache = {}
        memory_service.milvus_store = milvus_store
        embedding_client.provider = "unit"
        embedding_client.model = "handcrafted"
        embedding_client.dim = 3
        self.addCleanup(self._restore_runtime)
        self.addCleanup(self._drop_memory_collection)

        if not milvus_store.is_available:
            self.skipTest("Milvus endpoint is not reachable.")
        if not milvus_store.ensure_memory_collection():
            self.skipTest("Milvus memory collection could not be created.")

    def _dispose_db(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _drop_memory_collection(self) -> None:
        try:
            milvus_store.drop_collections(target="memory")
        except Exception:
            pass

    def _restore_runtime(self) -> None:
        milvus_store.enabled = self.original_store_state["enabled"]
        milvus_store.dim = self.original_store_state["dim"]
        milvus_store.collection_prefix = self.original_store_state["collection_prefix"]
        milvus_store._client = self.original_store_state["_client"]
        milvus_store._client_error = self.original_store_state["_client_error"]
        milvus_store._field_cache = self.original_store_state["_field_cache"]
        memory_service.milvus_store = self.original_store_state["memory_service_store"]
        embedding_client.provider = self.original_embedding_state["provider"]
        embedding_client.model = self.original_embedding_state["model"]
        embedding_client.dim = self.original_embedding_state["dim"]
        if self.original_vector_retrieval is None:
            os.environ.pop("MEMORY_VECTOR_RETRIEVAL_ENABLED", None)
        else:
            os.environ["MEMORY_VECTOR_RETRIEVAL_ENABLED"] = self.original_vector_retrieval

    def create_user(self) -> User:
        user = User(username="milvus-memory-eval", password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname="eval",
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=[],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode="long_term",
                    companion_style="gentle",
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_memory(self, user: User, *, memory_type: str, content: str, importance: int = 1) -> UserMemory:
        memory = UserMemory(
            user_id=user.id,
            memory_type=memory_type,
            title=content[:80],
            summary=content,
            content=content,
            importance=importance,
            visibility="user_visible",
            status="active",
            review_state="normal",
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def upsert_vectors(self, user: User, rows: list[tuple[UserMemory, list[float]]]) -> None:
        payload = []
        for memory, vector in rows:
            payload.append(
                {
                    "id": memory.id,
                    "memory_id": memory.id,
                    "user_id": user.id,
                    "memory_type": memory.memory_type,
                    "visibility": memory.visibility,
                    "status": memory.status,
                    "review_state": memory.review_state,
                    "title": memory.title or "",
                    "source": memory.source,
                    "embedding_key": embedding_client.embedding_key,
                    "updated_at": (memory.updated_at or utcnow()).isoformat(),
                    "content": memory.content,
                    "vector": vector,
                }
            )
        if not milvus_store.upsert_memory_vectors(payload):
            self.skipTest("Milvus memory vector upsert failed.")
        time.sleep(0.5)

    def test_milvus_vector_memory_recall_and_precision(self) -> None:
        user = self.create_user()
        trigger = self.add_memory(
            user,
            memory_type="recurring_trigger",
            content="final exam season tends to trigger panic",
        )
        strategy = self.add_memory(
            user,
            memory_type="support_strategy",
            content="slow grounding exercise helps after conflict",
        )
        relationship = self.add_memory(
            user,
            memory_type="relationship",
            content="conflict with mother is a recurring relationship theme",
        )
        decoy = self.add_memory(user, memory_type="profile", content="likes quiet mornings", importance=5)
        self.upsert_vectors(
            user,
            [
                (trigger, [1.0, 0.0, 0.0]),
                (strategy, [0.0, 1.0, 0.0]),
                (relationship, [0.0, 0.0, 1.0]),
                (decoy, [0.2, 0.2, 0.2]),
            ],
        )

        cases = [
            ("I am scared of finals again", [1.0, 0.0, 0.0], trigger.id),
            ("help me ground after the argument", [0.0, 1.0, 0.0], strategy.id),
            ("my mom and I had the same fight", [0.0, 0.0, 1.0], relationship.id),
        ]
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

        recall_at_5 = top5_hits / len(cases)
        precision_at_1 = top1_hits / len(cases)
        self.assertGreaterEqual(recall_at_5, 1.0)
        self.assertGreaterEqual(precision_at_1, 1.0)


if __name__ == "__main__":
    unittest.main()
