# 记忆系统优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix memory job failure recovery, push memory-type filtering into SQL, and remove N+1 embedding lookups without changing the public API.

**Architecture:** `memory_job_service.py` owns the job lifecycle and retry state. `memory_service.py` owns retrieval filtering and embedding indexing. Tests stay in the existing unittest suite, with one focused test per behavior so regressions are obvious.

**Tech Stack:** Python 3.13, SQLAlchemy 2.x, asyncio, unittest/pytest, existing FastAPI backend.

---

### Task 1: Stop `process_memory_job()` from doing an intermediate commit on failure

**Files:**
- Modify: `backend/tests/test_memory.py`
- Modify: `backend/app/services/memory_job_service.py`

- [ ] **Step 1: Add the failing regression test**

Add `ConversationTurn` and `utcnow` to the imports at the top of `backend/tests/test_memory.py`:

```python
from app.db.models import (
    Base,
    ConversationThread,
    ConversationTurn,
    Message,
    MoodLog,
    PendingMemoryJob,
    RiskEvent,
    User,
    UserMemory,
    UserProfile,
    UserSettings,
    utcnow,
)
```

Add this test method inside `ChatMemoryModeTests`:

```python
    async def test_failed_memory_job_does_not_issue_an_intermediate_commit(self) -> None:
        user, thread = self.create_user_with_thread(memory_mode="summary_only")
        turn = ConversationTurn(
            user_id=user.id,
            thread_id=thread.id,
            client_message_id="client-memory-job-failure",
            request_hash="hash-memory-job-failure",
            turn_status="completed",
            response_snapshot={},
        )
        assistant_message = Message(
            thread_id=thread.id,
            user_id=user.id,
            role="assistant",
            content="assistant reply",
            meta={},
        )
        self.db.add_all([turn, assistant_message])
        self.db.flush()

        job = PendingMemoryJob(
            user_id=user.id,
            thread_id=thread.id,
            turn_id=turn.id,
            assistant_message_id=assistant_message.id,
            job_type="memory_write",
            status="pending",
            attempt_count=0,
            max_attempts=1,
            next_run_at=utcnow(),
            payload={
                "should_write_memory": True,
                "memory_candidates": [{"memory_type": "session_summary", "content": "keep this"}],
                "session_summary": "keep this",
                "risk_level": "L0",
                "memory_policy": "write_safe_summary",
                "memory_mode": "summary_only",
            },
        )
        self.db.add(job)
        self.db.commit()

        with patch.object(self.db, "commit", wraps=self.db.commit) as commit_spy:
            with patch(
                "app.services.memory_job_service.upsert_memory_candidates",
                side_effect=RuntimeError("boom"),
            ):
                result = await process_memory_job(self.db, job.id)

        self.db.refresh(job)
        self.db.refresh(assistant_message)
        self.db.refresh(turn)

        self.assertIsNotNone(result)
        self.assertEqual(commit_spy.call_count, 1)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNone(job.locked_at)
        self.assertIsNone(job.locked_by)
        self.assertTrue((job.last_error or "").startswith("RuntimeError: boom"))
        self.assertEqual(assistant_message.meta["memory_job_status"], "failed")
        self.assertEqual(turn.response_snapshot["memory_job_status"], "failed")
```

- [ ] **Step 2: Run the test and confirm it fails on the current code**

Run:

```bash
cd backend && python -m pytest tests/test_memory.py::ChatMemoryModeTests::test_failed_memory_job_does_not_issue_an_intermediate_commit -v
```

Expected: FAIL with `AssertionError: 2 != 1` because `process_memory_job()` still commits once before the failure path and once in `_mark_job_failed()`.

- [ ] **Step 3: Remove the intermediate commit in `process_memory_job()`**

Update `backend/app/services/memory_job_service.py` so the non-`running` branch only mutates the job in memory and flushes, instead of committing before the business logic runs:

```python
    if job.status != "running":
        job.status = "running"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.locked_at = utcnow()
        job.locked_by = socket.gethostname()
        job.updated_at = utcnow()
        db.flush()
```

Keep the rest of the failure path unchanged: `rollback()` first, then `_mark_job_failed()` writes the final `pending`/`failed` state.

- [ ] **Step 4: Re-run the regression test**

Run:

```bash
cd backend && python -m pytest tests/test_memory.py::ChatMemoryModeTests::test_failed_memory_job_does_not_issue_an_intermediate_commit -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_memory.py backend/app/services/memory_job_service.py
git commit -m "fix: remove intermediate commit from memory job failure path"
```

---

### Task 2: Push memory-type filtering into `_base_memory_query()`

**Files:**
- Modify: `backend/tests/test_memory_service.py`
- Modify: `backend/app/services/memory_service.py`

- [ ] **Step 1: Add the failing tests**

No new imports are needed for these two assertions.

Add these two tests to `MemoryServiceTests`:

```python
    def test_summary_only_build_memory_index_respects_memory_types_before_limit(self) -> None:
        user = self.create_user(memory_mode="summary_only")
        for idx in range(200):
            self.add_memory(
                user,
                memory_type="preference",
                content=f"preference {idx}",
                importance=5,
            )
        summary = self.add_memory(
            user,
            memory_type="session_summary",
            content="exam stress summary",
            importance=1,
        )

        results = build_memory_index(self.db, user.id, memory_mode="summary_only", limit=20)

        self.assertEqual([item["memory_id"] for item in results], [summary.id])

    def test_summary_only_retrieve_memories_respects_memory_types_before_limit(self) -> None:
        user = self.create_user(memory_mode="summary_only")
        for idx in range(200):
            self.add_memory(
                user,
                memory_type="preference",
                content=f"preference {idx}",
                importance=5,
            )
        summary = self.add_memory(
            user,
            memory_type="session_summary",
            content="exam stress summary",
            importance=1,
        )

        results = retrieve_memories_for_turn(
            self.db,
            user_id=user.id,
            query="exam stress summary",
            memory_mode="summary_only",
            limit=5,
        )

        self.assertEqual([item["memory_id"] for item in results], [summary.id])
```

- [ ] **Step 2: Run the tests and confirm they fail on the current code**

Run:

```bash
cd backend && python -m pytest tests/test_memory_service.py::MemoryServiceTests::test_summary_only_build_memory_index_respects_memory_types_before_limit tests/test_memory_service.py::MemoryServiceTests::test_summary_only_retrieve_memories_respects_memory_types_before_limit -v
```

Expected: FAIL because `_base_memory_query()` still limits to 200 before the caller can narrow memory types, so `session_summary` is not guaranteed to survive the scan.

- [ ] **Step 3: Update `_base_memory_query()` and both callers**

Update `backend/app/services/memory_service.py` to accept an optional `memory_types` filter:

```python
def _base_memory_query(db: Session, user_id: str, memory_types: set[str] | None = None):
    now = utcnow()
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.status == "active",
        UserMemory.review_state != "do_not_use",
        or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
    )
    if memory_types is not None:
        allowed_types = sorted({memory_type for memory_type in memory_types if memory_type})
        if not allowed_types:
            return []
        stmt = stmt.where(UserMemory.memory_type.in_(allowed_types))
    return db.scalars(
        stmt.order_by(desc(UserMemory.importance), desc(UserMemory.updated_at)).limit(200)
    )
```

Update the callers so they pass the allowed type set instead of filtering in Python:

```python
    for memory in _base_memory_query(db, user_id, memory_types=allowed_types):
```

Use that form in both `build_memory_index()` and `retrieve_memories_for_turn()`. Keep the visibility checks and scoring logic unchanged.

- [ ] **Step 4: Re-run the targeted tests and the nearby existing memory-mode test**

Run:

```bash
cd backend && python -m pytest \
  tests/test_memory_service.py::MemoryServiceTests::test_summary_only_build_memory_index_respects_memory_types_before_limit \
  tests/test_memory_service.py::MemoryServiceTests::test_summary_only_retrieve_memories_respects_memory_types_before_limit \
  tests/test_memory_service.py::MemoryServiceTests::test_memory_modes_and_high_risk_internal_safety_filtering \
  -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_memory_service.py backend/app/services/memory_service.py
git commit -m "fix: push memory type filters into base memory query"
```

---

### Task 3: Replace the per-memory `MemoryEmbedding` lookup with a batch query

**Files:**
- Modify: `backend/tests/test_memory_service.py`
- Modify: `backend/app/services/memory_service.py`

- [ ] **Step 1: Add the failing batch-query test**

Add `asyncio`, `event`, and `MemoryEmbedding` to the imports in `backend/tests/test_memory_service.py` if they are not already present:

```python
import asyncio

from sqlalchemy import create_engine, event, select

from app.db.models import MemoryEmbedding
```

Add this test to `MemoryServiceTests`:

```python
    def test_index_memory_embeddings_batches_existing_embedding_lookup(self) -> None:
        user = self.create_user(memory_mode="long_term")
        first = self.add_memory(user, memory_type="preference", content="prefers grounding first")
        second = self.add_memory(user, memory_type="support_strategy", content="uses box breathing")
        select_statements: list[str] = []

        class FakeEmbeddingClient:
            is_configured = True
            model = "test-model"
            embedding_key = "local:test-model:3"

            async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
                return [[float(index + 1)] * 3 for index, _ in enumerate(texts)]

        fake_milvus_store = SimpleNamespace(upsert_memory_vectors=lambda rows: True)

        def _track_sql(conn, cursor, statement, parameters, context, executemany) -> None:
            sql = statement.lower()
            if sql.startswith("select") and "from memory_embeddings" in sql:
                select_statements.append(statement)

        original_embeddings_enabled = os.environ.get("MEMORY_EMBEDDINGS_ENABLED")
        original_embedding_client = memory_service.embedding_client
        original_milvus_store = memory_service.milvus_store
        event.listen(self.engine, "before_cursor_execute", _track_sql)
        os.environ["MEMORY_EMBEDDINGS_ENABLED"] = "1"
        memory_service.embedding_client = FakeEmbeddingClient()
        memory_service.milvus_store = fake_milvus_store
        try:
            asyncio.run(memory_service.index_memory_embeddings(self.db, [first, second]))
        finally:
            event.remove(self.engine, "before_cursor_execute", _track_sql)
            memory_service.embedding_client = original_embedding_client
            memory_service.milvus_store = original_milvus_store
            if original_embeddings_enabled is None:
                os.environ.pop("MEMORY_EMBEDDINGS_ENABLED", None)
            else:
                os.environ["MEMORY_EMBEDDINGS_ENABLED"] = original_embeddings_enabled

        embeddings = list(
            self.db.scalars(
                select(MemoryEmbedding).where(
                    MemoryEmbedding.embedding_key == FakeEmbeddingClient.embedding_key,
                    MemoryEmbedding.memory_id.in_([first.id, second.id]),
                )
            )
        )

        self.assertEqual(len(select_statements), 1)
        self.assertEqual({row.memory_id for row in embeddings}, {first.id, second.id})
```

- [ ] **Step 2: Run the test and confirm it fails on the current code**

Run:

```bash
cd backend && python -m pytest tests/test_memory_service.py::MemoryServiceTests::test_index_memory_embeddings_batches_existing_embedding_lookup -v
```

Expected: FAIL because the current code still runs a `SELECT` against `memory_embeddings` once per memory, so the SQL counter reports more than one select.

- [ ] **Step 3: Replace the N+1 lookup with a single batch query**

Update `backend/app/services/memory_service.py` so `index_memory_embeddings()` loads all existing embeddings first, keyed by `memory_id`, before the update loop:

```python
    memory_ids = [memory.id for memory in active_memories]
    existing_rows = list(
        db.scalars(
            select(MemoryEmbedding)
            .where(
                MemoryEmbedding.user_id == active_memories[0].user_id,
                MemoryEmbedding.embedding_key == embedding_client.embedding_key,
                MemoryEmbedding.memory_id.in_(memory_ids),
            )
            .order_by(desc(MemoryEmbedding.updated_at), desc(MemoryEmbedding.created_at))
        )
    )
    existing_by_memory_id: dict[str, MemoryEmbedding] = {}
    for row in existing_rows:
        existing_by_memory_id.setdefault(row.memory_id, row)
```

Then replace the inner `db.scalar(select(...))` call with a dictionary lookup:

```python
        existing = existing_by_memory_id.get(memory.id)
        if existing is None:
            db.add(
                MemoryEmbedding(
                    memory_id=memory.id,
                    user_id=memory.user_id,
                    embedding=vector,
                    embedding_model=embedding_client.model,
                    embedding_key=embedding_client.embedding_key,
                    content_hash=content_hash,
                )
            )
        else:
            existing.embedding = vector
            existing.embedding_model = embedding_client.model
            existing.content_hash = content_hash
            existing.updated_at = utcnow()
```

Keep the Milvus upsert and `db.flush()` behavior unchanged.

- [ ] **Step 4: Re-run the batch-query test**

Run:

```bash
cd backend && python -m pytest tests/test_memory_service.py::MemoryServiceTests::test_index_memory_embeddings_batches_existing_embedding_lookup -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_memory_service.py backend/app/services/memory_service.py
git commit -m "fix: batch memory embedding lookup"
```

---

### Task 4: Run the focused regression suite

**Files:**
- None

- [ ] **Step 1: Run the focused memory suite**

Run:

```bash
cd backend && python -m pytest tests/test_memory.py tests/test_memory_service.py -v
```

Expected: All tests PASS.

- [ ] **Step 2: Confirm the working tree is clean after the last fix**

Run:

```bash
git status --short
```

Expected: no unstaged changes from the memory optimization work.
