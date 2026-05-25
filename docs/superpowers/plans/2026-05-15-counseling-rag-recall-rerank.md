# Counseling RAG Recall Rerank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the prepared counseling corpus into a controlled runtime RAG pipeline: user input -> query embedding -> Milvus recall -> safe filtering -> explicit rerank -> prompt packing -> model answer.

**Architecture:** Keep risk control as the first gate and keep Milvus as a rebuildable recall index. Add a focused reranking module that scores already-recalled safe counseling chunks, then let `counseling_vector_service.py` orchestrate retrieval while `response_nodes.py` packs only the selected display text into the model prompt.

**Tech Stack:** Python 3.13, LangGraph state nodes, BGE-M3 local embedding, Milvus vector search, dataclasses, pytest/unittest.

---

## File Structure

- Create: `backend/app/services/counseling_reranker.py`
  - Pure scoring and selection functions for RAG candidates.
  - No Milvus, embedding, database, or settings dependency.
- Modify: `backend/app/services/counseling_vector_service.py`
  - Keep policy gates, embedding, Milvus recall, safety filtering, and trace orchestration.
  - Replace current quota-only selection with reranker selection.
- Modify: `backend/app/graphs/nodes/rag_nodes.py`
  - Serialize rerank metadata into `retrieved_counseling_examples`.
- Modify: `backend/app/graphs/nodes/response_nodes.py`
  - Keep grouped RAG prompt sections, add compact use/rank hints, and ensure prompt packing uses `display_text`.
- Modify: `backend/tests/test_counseling_milvus_plan.py`
  - Add recall/rerank orchestration tests.
- Create: `backend/tests/test_counseling_reranker.py`
  - Unit tests for reranker scoring, diversity, chunk-type quotas, and low-score fallback.
- Modify: `backend/tests/test_conversation_control_rag.py`
  - Add prompt packing and risk-gate regression tests.
- Optional Modify: `backend/README.md`
  - Document runtime RAG stages and smoke command.

---

### Task 1: Add A Pure Reranker Module

**Files:**
- Create: `backend/app/services/counseling_reranker.py`
- Create: `backend/tests/test_counseling_reranker.py`

- [ ] **Step 1: Write failing tests for scoring and selection**

Create `backend/tests/test_counseling_reranker.py`:

```python
from __future__ import annotations

import unittest

from app.services.counseling_reranker import (
    RerankCandidate,
    rerank_counseling_candidates,
)


class CounselingRerankerTests(unittest.TestCase):
    def _candidate(
        self,
        chunk_id: str,
        *,
        score: float,
        mode: str = "soothe",
        chunk_type: str = "turn_pair",
        original_external_id: str | None = None,
        process_quality_score: float | None = None,
        intervention_tags: list[str] | None = None,
    ) -> RerankCandidate:
        return RerankCandidate(
            chunk_id=chunk_id,
            vector_score=score,
            mode=mode,
            chunk_type=chunk_type,
            original_external_id=original_external_id or chunk_id,
            source_key="smilechat",
            display_text=f"{chunk_type} display {chunk_id}",
            content=f"{chunk_type} content {chunk_id}",
            intervention_tags=intervention_tags or [],
            style_tags=["supportive"],
            scenario_tags=[],
            quality_score=None,
            safety_score=None,
            process_quality_score=process_quality_score,
        )

    def test_default_selection_prefers_process_plus_turns(self) -> None:
        candidates = [
            self._candidate("turn-high", score=0.95, chunk_type="turn_pair"),
            self._candidate("process-mid", score=0.82, chunk_type="process_segment", process_quality_score=0.9),
            self._candidate("turn-mid", score=0.8, chunk_type="turn_pair"),
            self._candidate("session-high", score=0.99, chunk_type="session_sketch"),
        ]

        selected = rerank_counseling_candidates(
            candidates,
            query="我最近压力很大，晚上睡不好",
            mode="soothe",
            limit=3,
        )

        self.assertEqual([item.chunk_type for item in selected], ["process_segment", "turn_pair", "turn_pair"])
        self.assertEqual(selected[0].chunk_id, "process-mid")
        self.assertGreater(selected[0].rerank_score, selected[1].rerank_score)
        self.assertIn("chunk_type_quota", selected[0].rerank_reasons)

    def test_continuation_selection_includes_session_sketch(self) -> None:
        candidates = [
            self._candidate("session", score=0.9, chunk_type="session_sketch", process_quality_score=0.8),
            self._candidate("process", score=0.88, chunk_type="process_segment", process_quality_score=0.8),
            self._candidate("turn", score=0.87, chunk_type="turn_pair"),
        ]

        selected = rerank_counseling_candidates(
            candidates,
            query="继续刚才那个工作压力的问题",
            mode="counseling",
            limit=3,
        )

        self.assertEqual([item.chunk_type for item in selected], ["session_sketch", "process_segment", "turn_pair"])

    def test_diversity_limits_same_original_dialogue(self) -> None:
        candidates = [
            self._candidate("a1", score=0.95, chunk_type="turn_pair", original_external_id="case-a"),
            self._candidate("a2", score=0.94, chunk_type="turn_pair", original_external_id="case-a"),
            self._candidate("a3", score=0.93, chunk_type="turn_pair", original_external_id="case-a"),
            self._candidate("b1", score=0.80, chunk_type="turn_pair", original_external_id="case-b"),
        ]

        selected = rerank_counseling_candidates(candidates, query="我很累", mode="vent", limit=3)

        self.assertLessEqual(
            sum(1 for item in selected if item.original_external_id == "case-a"),
            2,
        )
        self.assertTrue(any(item.original_external_id == "case-b" for item in selected))

    def test_low_score_candidates_can_be_dropped(self) -> None:
        candidates = [
            self._candidate("weak", score=0.12, chunk_type="turn_pair"),
        ]

        selected = rerank_counseling_candidates(
            candidates,
            query="我最近压力很大",
            mode="vent",
            limit=3,
            min_rerank_score=0.25,
        )

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `RerankCandidate`.

- [ ] **Step 3: Implement the reranker**

Create `backend/app/services/counseling_reranker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace


CHUNK_TYPES = {"turn_pair", "process_segment", "session_sketch"}
CONTINUATION_PATTERNS = ("继续", "还是", "刚才", "前面", "上次", "那个问题", "接着")


@dataclass(frozen=True)
class RerankCandidate:
    chunk_id: str
    vector_score: float
    mode: str
    chunk_type: str
    original_external_id: str
    source_key: str
    display_text: str
    content: str
    intervention_tags: list[str]
    style_tags: list[str]
    scenario_tags: list[str]
    quality_score: float | None = None
    safety_score: float | None = None
    process_quality_score: float | None = None
    rerank_score: float = 0.0
    rerank_reasons: tuple[str, ...] = ()


def _normalized_score(value: float | None) -> float:
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))


def _chunk_type(value: str | None) -> str:
    value = str(value or "turn_pair").strip()
    return value if value in CHUNK_TYPES else "turn_pair"


def _quota_for_query(query: str, limit: int) -> dict[str, int]:
    if any(pattern in query for pattern in CONTINUATION_PATTERNS):
        return {"session_sketch": 1, "process_segment": 1, "turn_pair": max(limit - 2, 0)}
    return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}


def _score_candidate(candidate: RerankCandidate, *, mode: str, query: str) -> RerankCandidate:
    reasons: list[str] = []
    score = 0.68 * _normalized_score(candidate.vector_score)

    if candidate.mode == mode:
        score += 0.12
        reasons.append("mode_match")
    elif candidate.mode in {"vent", "soothe", "counseling"} and mode == "companion":
        score += 0.04
        reasons.append("companion_mode_compatible")

    chunk_type = _chunk_type(candidate.chunk_type)
    if chunk_type == "process_segment":
        score += 0.08
        reasons.append("process_context")
    elif chunk_type == "session_sketch" and any(pattern in query for pattern in CONTINUATION_PATTERNS):
        score += 0.10
        reasons.append("continuation_session_map")

    quality = _normalized_score(candidate.quality_score)
    safety = _normalized_score(candidate.safety_score)
    process_quality = _normalized_score(candidate.process_quality_score)
    if quality:
        score += 0.04 * quality
        reasons.append("quality_score")
    if safety:
        score += 0.04 * safety
        reasons.append("safety_score")
    if process_quality:
        score += 0.06 * process_quality
        reasons.append("process_quality_score")

    if candidate.intervention_tags:
        score += min(len(set(candidate.intervention_tags)), 3) * 0.015
        reasons.append("intervention_tags")

    return replace(
        candidate,
        chunk_type=chunk_type,
        rerank_score=round(score, 4),
        rerank_reasons=tuple(reasons),
    )


def rerank_counseling_candidates(
    candidates: list[RerankCandidate],
    *,
    query: str,
    mode: str,
    limit: int,
    min_rerank_score: float = 0.0,
) -> list[RerankCandidate]:
    safe_limit = max(0, min(limit, 3))
    if safe_limit == 0:
        return []

    scored = [
        item
        for item in (_score_candidate(candidate, mode=mode, query=query) for candidate in candidates)
        if item.rerank_score >= min_rerank_score
    ]
    scored.sort(key=lambda item: (-item.rerank_score, -_normalized_score(item.vector_score), item.chunk_id))

    quota = _quota_for_query(query, safe_limit)
    selected: list[RerankCandidate] = []
    used_by_type = {chunk_type: 0 for chunk_type in quota}
    used_sources: dict[str, int] = {}

    def can_use(item: RerankCandidate, *, enforce_type: str | None) -> bool:
        if item in selected:
            return False
        if enforce_type and item.chunk_type != enforce_type:
            return False
        if used_sources.get(item.original_external_id, 0) >= 2:
            return False
        return True

    for desired_type, desired_count in quota.items():
        for item in scored:
            if used_by_type[desired_type] >= desired_count:
                break
            if not can_use(item, enforce_type=desired_type):
                continue
            selected.append(replace(item, rerank_reasons=(*item.rerank_reasons, "chunk_type_quota")))
            used_by_type[desired_type] += 1
            used_sources[item.original_external_id] = used_sources.get(item.original_external_id, 0) + 1
            if len(selected) >= safe_limit:
                return selected

    for item in scored:
        if len(selected) >= safe_limit:
            break
        if not can_use(item, enforce_type=None):
            continue
        selected.append(item)
        used_sources[item.original_external_id] = used_sources.get(item.original_external_id, 0) + 1

    return selected
```

- [ ] **Step 4: Run reranker tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/counseling_reranker.py backend/tests/test_counseling_reranker.py
git commit -m "feat: add counseling rag reranker"
```

---

### Task 2: Wire Reranker Into Counseling Retrieval

**Files:**
- Modify: `backend/app/services/counseling_vector_service.py`
- Modify: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write failing orchestration test**

In `backend/tests/test_counseling_milvus_plan.py`, add a test to `CounselingMilvusPlanTests`:

```python
    async def test_retrieval_trace_includes_recall_and_rerank_counts(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples
        original_rag_enabled = counseling_vector_service.settings.counseling_rag_enabled

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("weak", chunk_type="turn_pair", original_external_id="case-weak", score=0.1),
            self._hit("process", chunk_type="process_segment", original_external_id="case-process", score=0.86),
            self._hit("turn", chunk_type="turn_pair", original_external_id="case-turn", score=0.84),
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

        self.assertEqual(result.trace["recall_candidate_count"], 3)
        self.assertEqual(result.trace["safe_candidate_count"], 3)
        self.assertEqual(result.trace["reranked_count"], len(result.examples))
        self.assertTrue(all(example.process_quality_score is not None or example.chunk_type == "turn_pair" for example in result.examples))
        self.assertIn("rerank_score", result.trace["selected_examples"][0])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_trace_includes_recall_and_rerank_counts -q
```

Expected: FAIL because `recall_candidate_count`, `reranked_count`, or `selected_examples` are missing.

- [ ] **Step 3: Add conversion helpers in `counseling_vector_service.py`**

Add imports:

```python
from app.services.counseling_reranker import RerankCandidate, rerank_counseling_candidates
```

Add helpers near `_to_float()`:

```python
def _candidate_from_hit(hit: Any) -> RerankCandidate:
    return RerankCandidate(
        chunk_id=str(hit.entity.get("chunk_id") or hit.id or ""),
        vector_score=float(hit.score or 0.0),
        mode=str(hit.entity.get("mode") or ""),
        chunk_type=str(hit.entity.get("chunk_type") or "turn_pair"),
        original_external_id=str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or hit.id or ""),
        source_key=str(hit.entity.get("source_key") or ""),
        display_text=str(hit.entity.get("display_text") or ""),
        content=str(hit.entity.get("content") or ""),
        intervention_tags=_split_tags(hit.entity.get("intervention_tags")),
        style_tags=_split_tags(hit.entity.get("style_tags")),
        scenario_tags=_split_tags(hit.entity.get("scenario_tags")),
        quality_score=_to_float(hit.entity.get("quality_score")),
        safety_score=_to_float(hit.entity.get("safety_score")),
        process_quality_score=_to_float(hit.entity.get("process_quality_score")),
    )


def _hit_by_chunk_id(hits: list[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for hit in hits:
        chunk_id = str(hit.entity.get("chunk_id") or hit.id or "")
        if chunk_id and chunk_id not in indexed:
            indexed[chunk_id] = hit
    return indexed
```

- [ ] **Step 4: Replace quota-only selection with reranking**

Inside `retrieve_counseling_examples_with_trace()`, keep the current policy gates, query embedding, mode search, dedupe, and `counseling_example_is_safe()` filtering. After the recall loop:

```python
    trace["recall_candidate_count"] = len(seen_ids)
    trace["safe_candidate_count"] = len(hits)
    candidates = [_candidate_from_hit(hit) for hit in hits]
    reranked = rerank_counseling_candidates(
        candidates,
        query=query,
        mode=mode,
        limit=safe_limit,
        min_rerank_score=0.20,
    )
    hit_by_chunk_id = _hit_by_chunk_id(hits)
    selected_hits = [hit_by_chunk_id[item.chunk_id] for item in reranked if item.chunk_id in hit_by_chunk_id]
    trace["reranked_count"] = len(reranked)
    trace["selected_examples"] = [
        {
            "chunk_id": item.chunk_id,
            "chunk_type": item.chunk_type,
            "vector_score": round(item.vector_score, 4),
            "rerank_score": item.rerank_score,
            "rerank_reasons": list(item.rerank_reasons),
        }
        for item in reranked
    ]
```

Then build `CounselingExampleHit` from `selected_hits`. When creating each example, look up its matching reranked item and populate new metadata in Task 3.

- [ ] **Step 5: Run focused orchestration test**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_trace_includes_recall_and_rerank_counts -q
```

Expected: PASS.

- [ ] **Step 6: Run existing RAG tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/counseling_vector_service.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: rerank counseling rag recall candidates"
```

---

### Task 3: Carry Rerank Metadata To Prompt Packing

**Files:**
- Modify: `backend/app/services/counseling_vector_service.py`
- Modify: `backend/app/graphs/nodes/rag_nodes.py`
- Modify: `backend/app/graphs/nodes/response_nodes.py`
- Modify: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Extend `CounselingExampleHit`**

In `backend/app/services/counseling_vector_service.py`, add fields:

```python
    rerank_score: float | None = None
    rerank_reasons: list[str] | None = None
```

When building examples after rerank, set:

```python
                rerank_score=reranked_by_chunk_id.get(chunk_id).rerank_score if chunk_id in reranked_by_chunk_id else None,
                rerank_reasons=list(reranked_by_chunk_id.get(chunk_id).rerank_reasons) if chunk_id in reranked_by_chunk_id else [],
```

- [ ] **Step 2: Serialize metadata in `rag_nodes.py`**

Extend `example_hit_to_dict()`:

```python
        "rerank_score": getattr(example, "rerank_score", None),
        "rerank_reasons": list(getattr(example, "rerank_reasons", None) or []),
```

- [ ] **Step 3: Write prompt-packing regression test**

In `backend/tests/test_conversation_control_rag.py`, add:

```python
    def test_rag_prompt_packs_display_text_and_rank_hints(self) -> None:
        from app.graphs.nodes.response_nodes import examples_text_from_state

        state = self.make_state(
            "我最近压力很大",
            retrieved_counseling_examples=[
                {
                    "chunk_type": "process_segment",
                    "display_text": "阶段：exploration\n咨询师动作线索：reflection",
                    "content": "完整长对话不应该进入 prompt " * 50,
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.82,
                    "rerank_score": 0.91,
                    "rerank_reasons": ["mode_match", "process_context", "chunk_type_quota"],
                    "intervention_tags": ["reflection"],
                }
            ],
        )

        text = examples_text_from_state(state)

        self.assertIn("Rerank: 0.9100", text)
        self.assertIn("Use hints: mode_match, process_context, chunk_type_quota", text)
        self.assertIn("阶段：exploration", text)
        self.assertNotIn("完整长对话不应该进入 prompt 完整长对话不应该进入 prompt", text)
```

- [ ] **Step 4: Run test to verify it fails**

Run:

```bash
cd backend && python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_rag_prompt_packs_display_text_and_rank_hints -q
```

Expected: FAIL because `Rerank` and `Use hints` are not formatted yet.

- [ ] **Step 5: Update prompt reference formatting**

In `backend/app/graphs/nodes/response_nodes.py`, update `_rag_reference_line()`:

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

- [ ] **Step 6: Run prompt tests**

Run:

```bash
cd backend && python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_rag_prompt_packs_display_text_and_rank_hints tests/test_conversation_control_rag.py::ConversationControlRagTests::test_generator_uses_state_examples_without_retrieving_again -q
```

Expected: PASS.

- [ ] **Step 7: Run focused RAG suite**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/counseling_vector_service.py backend/app/graphs/nodes/rag_nodes.py backend/app/graphs/nodes/response_nodes.py backend/tests/test_conversation_control_rag.py
git commit -m "feat: expose counseling rag rerank metadata"
```

---

### Task 4: Add Runtime Smoke Command And Observability Notes

**Files:**
- Modify: `backend/README.md`

- [ ] **Step 1: Add a manual smoke command section**

In `backend/README.md`, under the counseling Milvus/RAG section, add:

````markdown
### Counseling RAG runtime smoke

After the counseling corpus is embedded, test the runtime path with:

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
        "hit_count": len(result.get("retrieved_counseling_examples") or []),
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected: `rag_used=true`, `hit_count` up to 3, and trace fields including `embedding_duration_ms`, `milvus_duration_ms`, `recall_candidate_count`, `safe_candidate_count`, `reranked_count`, and `selected_examples`.
````

- [ ] **Step 2: Run docs-free verification**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 3: Run formatting check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Commit docs**

```bash
git add backend/README.md
git commit -m "docs: add counseling rag runtime smoke"
```

---

## Acceptance Criteria

- Low-risk support turns can run the full path: user text -> query embedding -> Milvus recall -> safety filter -> rerank -> prompt references.
- `L2/L3` and blocked `control_category` paths still skip RAG before embedding.
- Retrieval trace exposes enough data to debug misses: mode list, recall count, safe count, reranked count, selected examples, chunk type counts, embedding duration, Milvus duration.
- Final prompt uses grouped references and compact `display_text`, not full long retrieval text.
- Reranker is deterministic, unit-tested, and independent from Milvus/embedding.
- Existing copy-leak validator remains the final guard.

## Verification Commands

Run focused tests:

```bash
cd backend && python -m pytest tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Run whitespace check:

```bash
git diff --check
```

Run a live smoke only when local embedding and Milvus are configured:

```powershell
cd backend
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

- Spec coverage: This plan covers the requested runtime RAG chain: input embedding, recall, rerank, prompt composition, and model-answer readiness. It does not rework corpus preparation because data prep is already complete.
- Placeholder scan: No unresolved placeholder markers are present.
- Type consistency: `RerankCandidate`, `rerank_score`, and `rerank_reasons` are introduced before downstream tasks use them.
- Scope check: This is one bounded backend plan. It intentionally excludes knowledge RAG, memory retrieval, and risk-control redesign internals.
