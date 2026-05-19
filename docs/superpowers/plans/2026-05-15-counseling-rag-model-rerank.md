# Counseling RAG Model Rerank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local model reranker to the counseling RAG path so user input is embedded, recalled from Milvus, reranked with `BAAI/bge-reranker-v2-m3`, lightly policy-shaped, and packed into the dialogue prompt.

**Architecture:** Keep risk and control gates before embedding or reranking. Keep Milvus as the recall layer and add `counseling_reranker.py` plus a subprocess worker so reranker model loading does not destabilize the API process on Windows/Python 3.13. If reranking is disabled, times out, or fails, retrieval falls back to the current chunk-type quota selector.

**Tech Stack:** Python 3.13, FastAPI/LangGraph backend, local BGE-M3 embeddings, Milvus, `transformers`, `torch`, `BAAI/bge-reranker-v2-m3`, pytest/unittest.

---

## File Structure

- Modify: `backend/app/core/config.py`
  - Add counseling reranker runtime configuration.
- Modify: `backend/.env.example`
  - Document default reranker flags and model settings.
- Create: `backend/app/services/counseling_reranker.py`
  - Public async reranker client, data classes, fallback selectors, worker protocol.
- Create: `backend/app/services/local_reranker_worker.py`
  - Subprocess worker that loads `AutoTokenizer` and `AutoModelForSequenceClassification`.
- Modify: `backend/app/services/counseling_vector_service.py`
  - Use larger recall, call model reranker, fallback to quota selector, expose trace fields.
- Modify: `backend/app/graphs/nodes/rag_nodes.py`
  - Serialize rerank metadata for prompt packing and frontend trace inspection.
- Modify: `backend/app/graphs/nodes/response_nodes.py`
  - Pack rerank score/reasons while still preferring `display_text`.
- Create: `backend/tests/test_counseling_reranker.py`
  - Unit tests for reranker client behavior without loading a real model.
- Modify: `backend/tests/test_counseling_milvus_plan.py`
  - Integration-style tests for retrieval orchestration and fallback.
- Modify: `backend/tests/test_conversation_control_rag.py`
  - Prompt packing regression for rerank metadata.
- Modify: `backend/README.md`
  - Add model rerank smoke command and operational notes.

---

### Task 1: Add Reranker Configuration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_embedding_service.py`

- [ ] **Step 1: Write failing configuration test**

Append this test to `backend/tests/test_embedding_service.py`:

```python
def test_counseling_reranker_settings_have_defaults() -> None:
    from app.core.config import load_settings

    settings = load_settings()

    self_assertions = [
        settings.counseling_rerank_enabled is False,
        settings.counseling_rerank_model == "BAAI/bge-reranker-v2-m3",
        settings.counseling_recall_top_n == 40,
        settings.counseling_rerank_top_n == 12,
        settings.counseling_rerank_batch_size == 8,
        settings.counseling_rerank_max_length == 1024,
        settings.counseling_rerank_timeout_seconds == 20.0,
    ]
    assert all(self_assertions)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_embedding_service.py::test_counseling_reranker_settings_have_defaults -q
```

Expected: FAIL with `AttributeError` for missing settings fields.

- [ ] **Step 3: Extend `Settings` dataclass**

In `backend/app/core/config.py`, add these fields after `embedding_query_cache_size`:

```python
    counseling_rerank_enabled: bool
    counseling_rerank_model: str
    counseling_recall_top_n: int
    counseling_rerank_top_n: int
    counseling_rerank_batch_size: int
    counseling_rerank_max_length: int
    counseling_rerank_timeout_seconds: float
```

In `load_settings()`, add these values after `embedding_query_cache_size`:

```python
        counseling_rerank_enabled=os.getenv("COUNSELING_RERANK_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
        counseling_rerank_model=os.getenv("COUNSELING_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
        counseling_recall_top_n=int(os.getenv("COUNSELING_RECALL_TOP_N", "40")),
        counseling_rerank_top_n=int(os.getenv("COUNSELING_RERANK_TOP_N", "12")),
        counseling_rerank_batch_size=int(os.getenv("COUNSELING_RERANK_BATCH_SIZE", "8")),
        counseling_rerank_max_length=int(os.getenv("COUNSELING_RERANK_MAX_LENGTH", "1024")),
        counseling_rerank_timeout_seconds=float(os.getenv("COUNSELING_RERANK_TIMEOUT_SECONDS", "20")),
```

- [ ] **Step 4: Document env defaults**

In `backend/.env.example`, add:

```dotenv
COUNSELING_RERANK_ENABLED=0
COUNSELING_RERANK_MODEL=BAAI/bge-reranker-v2-m3
COUNSELING_RECALL_TOP_N=40
COUNSELING_RERANK_TOP_N=12
COUNSELING_RERANK_BATCH_SIZE=8
COUNSELING_RERANK_MAX_LENGTH=1024
COUNSELING_RERANK_TIMEOUT_SECONDS=20
```

- [ ] **Step 5: Run focused test**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_embedding_service.py::test_counseling_reranker_settings_have_defaults -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/config.py backend/.env.example backend/tests/test_embedding_service.py
git commit -m "feat: add counseling reranker settings"
```

---

### Task 2: Build The Local Model Reranker Client

**Files:**
- Create: `backend/app/services/counseling_reranker.py`
- Create: `backend/app/services/local_reranker_worker.py`
- Create: `backend/tests/test_counseling_reranker.py`

- [ ] **Step 1: Write failing reranker client tests**

Create `backend/tests/test_counseling_reranker.py`:

```python
from __future__ import annotations

import unittest

from app.services.counseling_reranker import (
    RerankCandidate,
    RerankResult,
    fallback_select_candidates,
    model_reranker,
)


class CounselingModelRerankerTests(unittest.IsolatedAsyncioTestCase):
    def candidate(
        self,
        chunk_id: str,
        *,
        vector_score: float,
        chunk_type: str = "turn_pair",
        original_external_id: str | None = None,
    ) -> RerankCandidate:
        return RerankCandidate(
            chunk_id=chunk_id,
            content=f"用户：我很累\n咨询回应：{chunk_id}",
            display_text=f"display {chunk_id}",
            vector_score=vector_score,
            mode="soothe",
            chunk_type=chunk_type,
            original_external_id=original_external_id or chunk_id,
            source_key="smilechat",
        )

    def test_fallback_selects_process_plus_turn_pair(self) -> None:
        candidates = [
            self.candidate("session", vector_score=0.99, chunk_type="session_sketch"),
            self.candidate("process", vector_score=0.80, chunk_type="process_segment"),
            self.candidate("turn-1", vector_score=0.79, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.78, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates(candidates, query="我最近压力很大", limit=3)

        self.assertEqual([item.chunk_type for item in selected], ["process_segment", "turn_pair", "turn_pair"])

    def test_fallback_continuation_includes_session_sketch(self) -> None:
        candidates = [
            self.candidate("session", vector_score=0.70, chunk_type="session_sketch"),
            self.candidate("process", vector_score=0.69, chunk_type="process_segment"),
            self.candidate("turn", vector_score=0.68, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates(candidates, query="继续刚才的问题", limit=3)

        self.assertEqual([item.chunk_type for item in selected], ["session_sketch", "process_segment", "turn_pair"])

    async def test_rerank_uses_worker_scores_when_available(self) -> None:
        original_score_pairs = model_reranker._score_pairs

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            return [0.1, 0.9, 0.4]

        candidates = [
            self.candidate("a", vector_score=0.95),
            self.candidate("b", vector_score=0.70),
            self.candidate("c", vector_score=0.80),
        ]
        model_reranker._score_pairs = fake_score_pairs
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=2,
                timeout_seconds=1.0,
            )
        finally:
            model_reranker._score_pairs = original_score_pairs

        self.assertIsInstance(result, RerankResult)
        self.assertEqual(result.status, "hit")
        self.assertEqual([item.chunk_id for item in result.candidates], ["b", "c"])
        self.assertEqual(result.candidates[0].rerank_score, 0.9)
        self.assertIn("model_rerank", result.candidates[0].rerank_reasons)

    async def test_rerank_falls_back_when_worker_unavailable(self) -> None:
        original_score_pairs = model_reranker._score_pairs

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            return None

        candidates = [
            self.candidate("process", vector_score=0.8, chunk_type="process_segment"),
            self.candidate("turn", vector_score=0.7, chunk_type="turn_pair"),
        ]
        model_reranker._score_pairs = fake_score_pairs
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=2,
                timeout_seconds=1.0,
            )
        finally:
            model_reranker._score_pairs = original_score_pairs

        self.assertEqual(result.status, "fallback")
        self.assertEqual([item.chunk_id for item in result.candidates], ["process", "turn"])
        self.assertEqual(result.reason, "reranker_unavailable")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_counseling_reranker.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.counseling_reranker'`.

- [ ] **Step 3: Implement `counseling_reranker.py`**

Create `backend/app/services/counseling_reranker.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
import logging
import os
import sys
from time import perf_counter
from typing import Any

from app.core.config import BASE_DIR, settings


logger = logging.getLogger(__name__)
CHUNK_TYPES = {"turn_pair", "process_segment", "session_sketch"}
CONTINUATION_PATTERNS = ("继续", "还是", "刚才", "前面", "上次", "那个问题", "接着")


@dataclass(frozen=True)
class RerankCandidate:
    chunk_id: str
    content: str
    display_text: str
    vector_score: float
    mode: str
    chunk_type: str
    original_external_id: str
    source_key: str
    rerank_score: float | None = None
    rerank_reasons: list[str] | None = None


@dataclass(frozen=True)
class RerankResult:
    candidates: list[RerankCandidate]
    status: str
    reason: str
    duration_ms: int
    scored_count: int


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _chunk_type(value: str | None) -> str:
    normalized = str(value or "turn_pair").strip()
    return normalized if normalized in CHUNK_TYPES else "turn_pair"


def _quota_for_query(query: str, limit: int) -> dict[str, int]:
    if any(pattern in query for pattern in CONTINUATION_PATTERNS):
        return {"session_sketch": 1, "process_segment": 1, "turn_pair": max(limit - 2, 0)}
    return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}


def fallback_select_candidates(candidates: list[RerankCandidate], *, query: str, limit: int) -> list[RerankCandidate]:
    safe_limit = max(0, min(limit, 3))
    sorted_candidates = sorted(candidates, key=lambda item: (-float(item.vector_score or 0.0), item.chunk_id))
    quota = _quota_for_query(query, safe_limit)
    selected: list[RerankCandidate] = []
    used_by_type = {chunk_type: 0 for chunk_type in quota}
    used_sources: dict[str, int] = {}

    def can_use(item: RerankCandidate, *, desired_type: str | None) -> bool:
        if item in selected:
            return False
        if desired_type and _chunk_type(item.chunk_type) != desired_type:
            return False
        if used_sources.get(item.original_external_id, 0) >= 2:
            return False
        return True

    for desired_type, desired_count in quota.items():
        for item in sorted_candidates:
            if used_by_type[desired_type] >= desired_count:
                break
            if not can_use(item, desired_type=desired_type):
                continue
            selected.append(
                replace(
                    item,
                    chunk_type=_chunk_type(item.chunk_type),
                    rerank_score=float(item.vector_score or 0.0),
                    rerank_reasons=["fallback_quota", desired_type],
                )
            )
            used_by_type[desired_type] += 1
            used_sources[item.original_external_id] = used_sources.get(item.original_external_id, 0) + 1
            if len(selected) >= safe_limit:
                return selected

    for item in sorted_candidates:
        if len(selected) >= safe_limit:
            break
        if not can_use(item, desired_type=None):
            continue
        selected.append(
            replace(
                item,
                chunk_type=_chunk_type(item.chunk_type),
                rerank_score=float(item.vector_score or 0.0),
                rerank_reasons=["fallback_vector_order"],
            )
        )
        used_sources[item.original_external_id] = used_sources.get(item.original_external_id, 0) + 1
    return selected


class CounselingModelReranker:
    def __init__(self) -> None:
        self.model_name = settings.counseling_rerank_model
        self.batch_size = max(settings.counseling_rerank_batch_size, 1)
        self._worker_process: Any | None = None
        self._worker_lock: asyncio.Lock | None = None

    @property
    def is_enabled(self) -> bool:
        return bool(settings.counseling_rerank_enabled and self.model_name)

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[RerankCandidate],
        limit: int,
        timeout_seconds: float | None = None,
    ) -> RerankResult:
        started_at = perf_counter()
        safe_limit = max(0, min(limit, 3))
        if safe_limit <= 0 or not candidates:
            return RerankResult([], "empty", "no_candidates", _elapsed_ms(started_at), 0)
        if not self.is_enabled:
            selected = fallback_select_candidates(candidates, query=query, limit=safe_limit)
            return RerankResult(selected, "fallback", "reranker_disabled", _elapsed_ms(started_at), 0)

        docs = [(candidate.display_text or candidate.content).strip() for candidate in candidates]
        scores = await self._score_pairs(
            query,
            docs,
            timeout_seconds=float(timeout_seconds or settings.counseling_rerank_timeout_seconds),
        )
        if scores is None or len(scores) != len(candidates):
            selected = fallback_select_candidates(candidates, query=query, limit=safe_limit)
            return RerankResult(selected, "fallback", "reranker_unavailable", _elapsed_ms(started_at), 0)

        scored = [
            replace(candidate, rerank_score=float(score), rerank_reasons=["model_rerank"])
            for candidate, score in zip(candidates, scores)
        ]
        scored.sort(key=lambda item: (-(item.rerank_score or 0.0), -float(item.vector_score or 0.0), item.chunk_id))
        selected = self._apply_diversity(scored, limit=safe_limit)
        return RerankResult(selected, "hit", "", _elapsed_ms(started_at), len(scored))

    def _apply_diversity(self, candidates: list[RerankCandidate], *, limit: int) -> list[RerankCandidate]:
        selected: list[RerankCandidate] = []
        used_sources: dict[str, int] = {}
        for candidate in candidates:
            if used_sources.get(candidate.original_external_id, 0) >= 2:
                continue
            selected.append(replace(candidate, chunk_type=_chunk_type(candidate.chunk_type)))
            used_sources[candidate.original_external_id] = used_sources.get(candidate.original_external_id, 0) + 1
            if len(selected) >= limit:
                break
        return selected

    async def _score_pairs(self, query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
        lock = self._get_worker_lock()
        async with lock:
            process = await self._ensure_worker()
            if process is None or process.stdin is None or process.stdout is None:
                return None
            payload = json.dumps({"query": query, "documents": documents}, ensure_ascii=True).encode("ascii") + b"\n"
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), timeout=max(timeout_seconds, 0.001))
            except (BrokenPipeError, ConnectionError, asyncio.TimeoutError) as exc:
                logger.warning("Local reranker worker request failed: %s", exc)
                await self.aclose()
                return None
            if not line:
                await self.aclose()
                return None
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                await self.aclose()
                return None
            if not isinstance(response, dict) or not response.get("ok"):
                logger.warning("Local reranker worker failed: %s", response)
                return None
            scores = response.get("scores")
            if not isinstance(scores, list):
                return None
            return [float(score) for score in scores]

    def _get_worker_lock(self) -> asyncio.Lock:
        if self._worker_lock is None:
            self._worker_lock = asyncio.Lock()
        return self._worker_lock

    async def _ensure_worker(self) -> Any | None:
        if self._worker_process is not None and self._worker_process.returncode is None:
            return self._worker_process
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self._worker_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.services.local_reranker_worker",
                cwd=str(BASE_DIR),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=8 * 1024 * 1024,
            )
        except Exception as exc:
            logger.warning("Local reranker worker start failed: %s", exc)
            self._worker_process = None
        return self._worker_process

    async def aclose(self) -> None:
        process = self._worker_process
        self._worker_process = None
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


model_reranker = CounselingModelReranker()
```

- [ ] **Step 4: Implement `local_reranker_worker.py`**

Create `backend/app/services/local_reranker_worker.py`:

```python
from __future__ import annotations

import json
import sys
from typing import Any


PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

from app.core.config import settings  # noqa: E402


def _emit(payload: dict[str, Any]) -> None:
    PROTOCOL_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    PROTOCOL_STDOUT.flush()


def _resolve_device() -> str:
    configured = (settings.local_embedding_device or "auto").strip().lower()
    if configured != "auto":
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _sigmoid(value: Any) -> float:
    import math

    raw = float(value)
    return 1.0 / (1.0 + math.exp(-raw))


def main() -> int:
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except Exception as exc:
        _emit({"ok": False, "error": f"reranker dependencies unavailable: {exc}"})
        return 1

    device = _resolve_device()
    model_kwargs: dict[str, Any] = {}
    if settings.local_embedding_cache_dir:
        model_kwargs["cache_dir"] = settings.local_embedding_cache_dir
    if device.startswith("cuda"):
        model_kwargs["torch_dtype"] = torch.float16

    try:
        tokenizer = AutoTokenizer.from_pretrained(settings.counseling_rerank_model, **model_kwargs)
        model = AutoModelForSequenceClassification.from_pretrained(settings.counseling_rerank_model, **model_kwargs)
        model.to(device)
        model.eval()
    except Exception as exc:
        _emit({"ok": False, "error": f"reranker model load failed: {exc}"})
        return 1

    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            query = str(request.get("query") or "").strip()
            documents = [str(item).strip() for item in request.get("documents", []) if str(item).strip()]
            pairs = [[query, document] for document in documents]
            scores: list[float] = []
            for start in range(0, len(pairs), max(settings.counseling_rerank_batch_size, 1)):
                batch = pairs[start : start + max(settings.counseling_rerank_batch_size, 1)]
                inputs = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=max(settings.counseling_rerank_max_length, 1),
                    return_tensors="pt",
                ).to(device)
                with torch.no_grad():
                    logits = model(**inputs).logits.squeeze(-1)
                if hasattr(logits, "tolist"):
                    raw_scores = logits.tolist()
                else:
                    raw_scores = [float(logits)]
                if not isinstance(raw_scores, list):
                    raw_scores = [raw_scores]
                scores.extend(round(_sigmoid(score), 6) for score in raw_scores)
            _emit({"ok": True, "scores": scores})
        except Exception as exc:
            _emit({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run unit tests**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_counseling_reranker.py -q
```

Expected: PASS. These tests monkeypatch `_score_pairs`, so they do not download or load the real reranker.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/counseling_reranker.py backend/app/services/local_reranker_worker.py backend/tests/test_counseling_reranker.py
git commit -m "feat: add local counseling model reranker"
```

---

### Task 3: Wire Model Rerank Into Counseling Retrieval

**Files:**
- Modify: `backend/app/services/counseling_vector_service.py`
- Modify: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write failing retrieval orchestration tests**

Add imports in `backend/tests/test_counseling_milvus_plan.py`:

```python
from app.services.counseling_reranker import RerankCandidate, RerankResult
```

Add this test to `CounselingMilvusPlanTests`:

```python
    async def test_retrieval_uses_model_reranker_when_enabled(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled
        original_rerank_enabled = counseling_vector_service.settings.counseling_rerank_enabled
        original_rerank = counseling_vector_service.model_reranker.rerank

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("low-vector", chunk_type="turn_pair", original_external_id="case-a", score=0.20),
            self._hit("best-model", chunk_type="turn_pair", original_external_id="case-b", score=0.19),
            self._hit("process", chunk_type="process_segment", original_external_id="case-c", score=0.18),
        ]

        async def fake_rerank(*, query: str, candidates: list[RerankCandidate], limit: int, timeout_seconds: float | None):
            by_id = {candidate.chunk_id: candidate for candidate in candidates}
            return RerankResult(
                candidates=[
                    by_id["best-model"].__class__(**{**by_id["best-model"].__dict__, "rerank_score": 0.97, "rerank_reasons": ["model_rerank"]}),
                    by_id["process"].__class__(**{**by_id["process"].__dict__, "rerank_score": 0.83, "rerank_reasons": ["model_rerank"]}),
                ],
                status="hit",
                reason="",
                duration_ms=7,
                scored_count=len(candidates),
            )

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        counseling_vector_service.model_reranker.rerank = fake_rerank
        object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", True)
        object.__setattr__(counseling_vector_service.settings, "counseling_rerank_enabled", True)
        try:
            state = AgentState(
                normalized_text="我最近压力很大",
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
            counseling_vector_service.model_reranker.rerank = original_rerank
            object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", original_rag_enabled)
            object.__setattr__(counseling_vector_service.settings, "counseling_rerank_enabled", original_rerank_enabled)

        self.assertEqual([example.chunk_id for example in result.examples], ["best-model", "process"])
        self.assertEqual(result.trace["rerank_status"], "hit")
        self.assertEqual(result.trace["rerank_scored_count"], 3)
        self.assertEqual(result.trace["selected_examples"][0]["rerank_score"], 0.97)
```

Add a fallback test:

```python
    async def test_retrieval_falls_back_when_model_reranker_fails(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled
        original_rerank_enabled = counseling_vector_service.settings.counseling_rerank_enabled
        original_rerank = counseling_vector_service.model_reranker.rerank

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        async def fake_rerank(*, query: str, candidates: list[RerankCandidate], limit: int, timeout_seconds: float | None):
            return RerankResult(candidates=[], status="fallback", reason="reranker_unavailable", duration_ms=5, scored_count=0)

        hits = [
            self._hit("session", chunk_type="session_sketch", original_external_id="case-a", score=0.99),
            self._hit("process", chunk_type="process_segment", original_external_id="case-b", score=0.80),
            self._hit("turn", chunk_type="turn_pair", original_external_id="case-c", score=0.79),
        ]

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        counseling_vector_service.model_reranker.rerank = fake_rerank
        object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", True)
        object.__setattr__(counseling_vector_service.settings, "counseling_rerank_enabled", True)
        try:
            state = AgentState(
                normalized_text="我最近压力很大",
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
            counseling_vector_service.model_reranker.rerank = original_rerank
            object.__setattr__(counseling_vector_service.settings, "counseling_rag_enabled", original_rag_enabled)
            object.__setattr__(counseling_vector_service.settings, "counseling_rerank_enabled", original_rerank_enabled)

        self.assertEqual([example.chunk_type for example in result.examples], ["process_segment", "turn_pair"])
        self.assertEqual(result.trace["rerank_status"], "fallback")
        self.assertEqual(result.trace["rerank_reason"], "reranker_unavailable")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_uses_model_reranker_when_enabled tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_falls_back_when_model_reranker_fails -q
```

Expected: FAIL because `counseling_vector_service` does not import or call `model_reranker`.

- [ ] **Step 3: Import reranker in `counseling_vector_service.py`**

Add:

```python
from app.services.counseling_reranker import RerankCandidate, fallback_select_candidates, model_reranker
```

- [ ] **Step 4: Add hit-to-candidate helpers**

In `backend/app/services/counseling_vector_service.py`, add near `_chunk_type_for_hit()`:

```python
def _candidate_from_hit(hit: Any) -> RerankCandidate:
    chunk_id = str(hit.entity.get("chunk_id") or hit.id or "")
    return RerankCandidate(
        chunk_id=chunk_id,
        content=str(hit.entity.get("content") or ""),
        display_text=str(hit.entity.get("display_text") or ""),
        vector_score=float(hit.score or 0.0),
        mode=str(hit.entity.get("mode") or ""),
        chunk_type=str(hit.entity.get("chunk_type") or "turn_pair"),
        original_external_id=str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or hit.id or ""),
        source_key=str(hit.entity.get("source_key") or ""),
    )


def _hits_by_chunk_id(hits: list[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for hit in hits:
        chunk_id = str(hit.entity.get("chunk_id") or hit.id or "")
        if chunk_id and chunk_id not in indexed:
            indexed[chunk_id] = hit
    return indexed
```

- [ ] **Step 5: Replace final quota selection with model rerank**

In `retrieve_counseling_examples_with_trace()`, replace:

```python
    hits = _select_hits_by_quota(hits, state=state, mode=mode, limit=safe_limit)
```

with:

```python
    trace["recall_candidate_count"] = len(seen_ids)
    trace["safe_candidate_count"] = len(hits)
    candidates = [_candidate_from_hit(hit) for hit in hits]
    rerank_result = await model_reranker.rerank(
        query=query,
        candidates=candidates[: max(settings.counseling_rerank_top_n, safe_limit)],
        limit=safe_limit,
        timeout_seconds=min(remaining_seconds(), settings.counseling_rerank_timeout_seconds),
    )
    if rerank_result.status in {"empty", "fallback"} and not rerank_result.candidates:
        selected_candidates = fallback_select_candidates(candidates, query=query, limit=safe_limit)
        rerank_status = "fallback"
        rerank_reason = rerank_result.reason or "empty_model_rerank"
    else:
        selected_candidates = rerank_result.candidates
        rerank_status = rerank_result.status
        rerank_reason = rerank_result.reason

    hit_by_chunk_id = _hits_by_chunk_id(hits)
    hits = [hit_by_chunk_id[item.chunk_id] for item in selected_candidates if item.chunk_id in hit_by_chunk_id]
    reranked_by_chunk_id = {item.chunk_id: item for item in selected_candidates}
    trace["rerank_status"] = rerank_status
    trace["rerank_reason"] = rerank_reason
    trace["rerank_duration_ms"] = rerank_result.duration_ms
    trace["rerank_scored_count"] = rerank_result.scored_count
    trace["selected_examples"] = [
        {
            "chunk_id": item.chunk_id,
            "chunk_type": item.chunk_type,
            "vector_score": round(float(item.vector_score or 0.0), 4),
            "rerank_score": round(float(item.rerank_score or 0.0), 4),
            "rerank_reasons": list(item.rerank_reasons or []),
        }
        for item in selected_candidates
    ]
```

When constructing each `CounselingExampleHit`, set `chunk_id` first and add:

```python
                rerank_score=reranked_by_chunk_id.get(chunk_id).rerank_score if chunk_id in reranked_by_chunk_id else None,
                rerank_reasons=list(reranked_by_chunk_id.get(chunk_id).rerank_reasons or []) if chunk_id in reranked_by_chunk_id else [],
```

Add fields to `CounselingExampleHit`:

```python
    rerank_score: float | None = None
    rerank_reasons: list[str] | None = None
```

- [ ] **Step 6: Increase recall pool size**

In `retrieve_counseling_examples_with_trace()`, replace:

```python
    per_query_limit = max(safe_limit * 6, 18)
```

with:

```python
    per_query_limit = max(settings.counseling_recall_top_n, safe_limit * 6, 18)
```

Keep the existing mode search order and safety filter.

- [ ] **Step 7: Run focused retrieval tests**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_uses_model_reranker_when_enabled tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_falls_back_when_model_reranker_fails -q
```

Expected: PASS.

- [ ] **Step 8: Run existing counseling retrieval tests**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_counseling_milvus_plan.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add backend/app/services/counseling_vector_service.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: apply model rerank to counseling rag"
```

---

### Task 4: Serialize And Prompt-Pack Rerank Metadata

**Files:**
- Modify: `backend/app/graphs/nodes/rag_nodes.py`
- Modify: `backend/app/graphs/nodes/response_nodes.py`
- Modify: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Add failing serialization and prompt tests**

In `backend/tests/test_conversation_control_rag.py`, add to `test_support_turn_can_use_authorized_fewshot_examples()` hit construction:

```python
            rerank_score=0.94,
            rerank_reasons=["model_rerank"],
```

Then assert:

```python
        self.assertEqual(result["retrieved_counseling_examples"][0]["rerank_score"], 0.94)
        self.assertEqual(result["retrieved_counseling_examples"][0]["rerank_reasons"], ["model_rerank"])
```

Add this prompt test:

```python
    def test_examples_text_includes_rerank_metadata_without_full_content(self) -> None:
        from app.graphs.nodes.response_nodes import examples_text_from_state

        state = self.make_state(
            "我最近压力很大",
            retrieved_counseling_examples=[
                {
                    "chunk_type": "process_segment",
                    "display_text": "阶段：exploration\n咨询师动作线索：reflection",
                    "content": "完整长对话不应该进入 prompt " * 20,
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.82,
                    "rerank_score": 0.91,
                    "rerank_reasons": ["model_rerank"],
                    "intervention_tags": ["reflection"],
                }
            ],
        )

        text = examples_text_from_state(state)

        self.assertIn("Rerank: 0.9100", text)
        self.assertIn("Use hints: model_rerank", text)
        self.assertIn("阶段：exploration", text)
        self.assertNotIn("完整长对话不应该进入 prompt 完整长对话不应该进入 prompt", text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_support_turn_can_use_authorized_fewshot_examples tests/test_conversation_control_rag.py::ConversationControlRagTests::test_examples_text_includes_rerank_metadata_without_full_content -q
```

Expected: FAIL because `example_hit_to_dict()` and `_rag_reference_line()` do not include rerank metadata.

- [ ] **Step 3: Serialize metadata in `rag_nodes.py`**

In `backend/app/graphs/nodes/rag_nodes.py`, extend `example_hit_to_dict()`:

```python
        "rerank_score": getattr(example, "rerank_score", None),
        "rerank_reasons": list(getattr(example, "rerank_reasons", None) or []),
```

- [ ] **Step 4: Add prompt formatting in `response_nodes.py`**

Update `_rag_reference_line()`:

```python
def _rag_reference_line(index: int, example: dict) -> list[str]:
    tags = ", ".join(str(tag) for tag in example.get("intervention_tags", []) if tag)
    reasons = ", ".join(str(reason) for reason in example.get("rerank_reasons", []) if reason)
    display_text = example.get("display_text") or example.get("content")
    rerank_score = example.get("rerank_score")
    lines = [
        f"[Reference {index}]",
        f"Source: {safe_trim(example.get('source_name') or example.get('source_key'), 40)}",
        f"Mode: {safe_trim(example.get('mode'), 20)}",
        f"Score: {float(example.get('score') or 0.0):.4f}",
    ]
    if rerank_score is not None:
        lines.append(f"Rerank: {float(rerank_score or 0.0):.4f}")
    if reasons:
        lines.append(f"Use hints: {safe_trim(reasons, 120)}")
    if tags:
        lines.append(f"Intervention tags: {safe_trim(tags, 80)}")
    lines.append(f"Content: {safe_trim(display_text, 300)}")
    return lines
```

- [ ] **Step 5: Run prompt tests**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_support_turn_can_use_authorized_fewshot_examples tests/test_conversation_control_rag.py::ConversationControlRagTests::test_examples_text_includes_rerank_metadata_without_full_content tests/test_conversation_control_rag.py::ConversationControlRagTests::test_examples_text_groups_layered_rag_references -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/graphs/nodes/rag_nodes.py backend/app/graphs/nodes/response_nodes.py backend/tests/test_conversation_control_rag.py
git commit -m "feat: expose counseling rerank metadata in prompts"
```

---

### Task 5: Add Runtime Smoke And Documentation

**Files:**
- Modify: `backend/README.md`

- [ ] **Step 1: Document model rerank operation**

In `backend/README.md`, under the counseling RAG/Milvus section, add:

````markdown
### Counseling RAG model rerank

Enable local model rerank after counseling chunks are indexed:

```dotenv
COUNSELING_RERANK_ENABLED=1
COUNSELING_RERANK_MODEL=BAAI/bge-reranker-v2-m3
COUNSELING_RECALL_TOP_N=40
COUNSELING_RERANK_TOP_N=12
COUNSELING_RERANK_BATCH_SIZE=8
COUNSELING_RERANK_MAX_LENGTH=1024
COUNSELING_RERANK_TIMEOUT_SECONDS=20
```

Runtime path:

```text
normalized_text -> BGE-M3 query embedding -> Milvus recall -> safety filter -> bge-reranker-v2-m3 -> diversity/fallback -> prompt references
```

Smoke command:

```powershell
@'
import asyncio
import json
from app.graphs.nodes.rag_nodes import example_retriever

async def main():
    state = {
        "normalized_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "user_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "risk_level": "L0",
        "route_priority": "P2_support",
        "control_category": "normal_support",
        "intent": "vent",
        "rag_policy": {"enabled": True},
        "audit_tags": [],
    }
    result = await example_retriever(state)
    print(json.dumps({
        "rag_used": result.get("rag_used"),
        "skip": result.get("rag_skipped_reason"),
        "trace": result.get("rag_trace_summary"),
        "hits": [
            {
                "chunk_id": item.get("chunk_id"),
                "chunk_type": item.get("chunk_type"),
                "score": item.get("score"),
                "rerank_score": item.get("rerank_score"),
                "rerank_reasons": item.get("rerank_reasons"),
            }
            for item in (result.get("retrieved_counseling_examples") or [])
        ],
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected when Milvus and local models are available: `rag_used=true`, `trace.rerank_status` is `hit` or `fallback`, and `selected_examples` contains `rerank_score` fields.
````

- [ ] **Step 2: Run focused tests**

Run:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_embedding_service.py tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 4: Optional live smoke**

Run only when `COUNSELING_RAG_ENABLED=1`, `COUNSELING_RERANK_ENABLED=1`, Milvus is reachable, and local model dependencies are installed:

```powershell
cd E:\心理咨询agent\backend
@'
import asyncio
import json
from app.graphs.nodes.rag_nodes import example_retriever

async def main():
    state = {
        "normalized_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "user_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "risk_level": "L0",
        "route_priority": "P2_support",
        "control_category": "normal_support",
        "intent": "vent",
        "rag_policy": {"enabled": True},
        "audit_tags": [],
    }
    print(json.dumps(await example_retriever(state), ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected: no exception; `rag_trace_summary` includes `rerank_status`, `rerank_duration_ms`, and `selected_examples`.

- [ ] **Step 5: Commit**

```powershell
git add backend/README.md
git commit -m "docs: add counseling model rerank smoke"
```

---

## Acceptance Criteria

- Low-risk counseling turns can run: query embedding -> Milvus recall -> safe filtering -> local model rerank -> prompt references.
- `L2/L3` and blocked control categories still skip before embedding, Milvus, and reranking.
- Reranker is behind `COUNSELING_RERANK_ENABLED`, so runtime can A/B compare with and without rerank.
- Reranker failures, startup errors, timeout, or bad score payloads fall back to deterministic chunk-type selection.
- Retrieval trace records `recall_candidate_count`, `safe_candidate_count`, `rerank_status`, `rerank_reason`, `rerank_duration_ms`, `rerank_scored_count`, and `selected_examples`.
- Prompt references use `display_text` first and include compact rerank metadata.
- Existing copy-leak validator remains unchanged and still blocks copied RAG content.

## Verification Commands

Run focused tests:

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_embedding_service.py tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Run whitespace check:

```powershell
git diff --check
```

Run live smoke when local dependencies and Milvus are available:

```powershell
cd E:\心理咨询agent\backend
@'
import asyncio
import json
from app.graphs.nodes.rag_nodes import example_retriever

async def main():
    state = {
        "normalized_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "user_text": "我最近压力很大，晚上睡不着，总觉得没人理解我",
        "risk_level": "L0",
        "route_priority": "P2_support",
        "control_category": "normal_support",
        "intent": "vent",
        "rag_policy": {"enabled": True},
        "audit_tags": [],
    }
    print(json.dumps(await example_retriever(state), ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

## Plan Self-Review

- Spec coverage: The plan covers the requested model rerank path and keeps the existing RAG safety gates, Milvus recall, layered chunk selection, prompt packing, and live smoke.
- Marker scan: No unresolved markers remain.
- Type consistency: `RerankCandidate`, `RerankResult`, `model_reranker`, `rerank_score`, and `rerank_reasons` are introduced before downstream files use them.
- Scope check: This is a bounded backend plan. It does not rebuild the already embedded corpus, change knowledge RAG, or redesign risk control.
