# Clarification Loop Memory Arbitration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind clarification answers into user context and make correction memories override conflicting older preferences.

**Architecture:** Reuse existing message metadata, `goal_state`, retrieval scoring, and `UserMemory` review fields. No schema changes; conflict handling is conservative and auditable.

**Tech Stack:** FastAPI service layer, LangGraph state, SQLAlchemy models, pytest/unittest.

---

### Task 1: 澄清答案进入 `goal_state`

**Files:**
- Modify: `backend/app/services/user_context_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/graphs/state.py`
- Test: `backend/tests/test_user_context_service.py`
- Test: `backend/tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

Add tests proving a previous assistant clarification causes the next user reply to become `goal_state["clarification_answer"]`, and that chat context passes this state into the runtime.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_user_context_service.py::UserContextServiceTests::test_build_goal_state_binds_previous_clarification_answer tests/test_memory.py::ChatMemoryIntegrationTests::test_clarification_answer_updates_goal_state_for_next_turn -q
```

Expected: fail because `build_goal_state()` does not accept or interpret `recent_messages`.

- [ ] **Step 3: Implement minimal binding**

Add recent-message inspection in `build_goal_state()`, pass serialized recent messages from chat context, and preserve clarification fields in graph result metadata.

- [ ] **Step 4: Run tests to verify green**

Run the same command and expect both tests to pass.

### Task 2: 澄清答案沉淀为目标候选

**Files:**
- Modify: `backend/app/graphs/nodes/memory_nodes.py`
- Test: `backend/tests/test_response_memory_continuity.py`

- [ ] **Step 1: Write failing test**

Add a long-term memory test where `goal_state["clarification_answer"]` creates a `goal` candidate even if `normalized_text` lacks explicit goal keywords.

- [ ] **Step 2: Run test to verify red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py::ResponseMemoryContinuityTests::test_memory_candidate_extract_creates_goal_from_clarification_answer -q
```

Expected: fail because no `goal` candidate is created.

- [ ] **Step 3: Implement minimal candidate generation**

Read `goal_state.clarification_answer` and append a high-value `goal` candidate before truncation.

- [ ] **Step 4: Run test to verify green**

Run the same command and expect it to pass.

### Task 3: 记忆冲突仲裁

**Files:**
- Modify: `backend/app/services/memory_service.py`
- Test: `backend/tests/test_memory_service.py`

- [ ] **Step 1: Write failing tests**

Add retrieval and upsert tests:
- explicit correction outranks conflicting old preference;
- writing correction marks conflicting preference as `needs_review` with `memory_conflict` metadata.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py::MemoryServiceTests::test_retrieve_uses_correction_over_conflicting_preference tests/test_memory_service.py::MemoryServiceTests::test_upsert_correction_marks_conflicting_preference_for_review -q
```

Expected: fail because conflict arbitration and marking are not implemented.

- [ ] **Step 3: Implement scoring and marking**

Add conservative conflict keyword detection, score boosts/penalties, `needs_review` penalty, and post-create/update conflict marking for new `correction` memories.

- [ ] **Step 4: Run tests to verify green**

Run the same command and expect both tests to pass.

### Task 4: 日志与回归

**Files:**
- Modify: `docs/dev-log/context-continuity-optimization.md`

- [ ] **Step 1: Update iteration log**

Add a section for “澄清闭环与记忆冲突仲裁”， covering implementation, fallback/safety, and tests.

- [ ] **Step 2: Run focused regression**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_user_context_service.py tests/test_response_memory_continuity.py tests/test_memory_service.py tests/test_memory.py tests/test_chat_idempotency.py tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Commit**

Stage only this feature's files and commit:

```powershell
git add backend/app/services/user_context_service.py backend/app/services/chat_service.py backend/app/services/graph_runtime.py backend/app/graphs/state.py backend/app/graphs/nodes/memory_nodes.py backend/app/services/memory_service.py backend/tests/test_user_context_service.py backend/tests/test_memory.py backend/tests/test_response_memory_continuity.py backend/tests/test_memory_service.py docs/superpowers/specs/2026-05-13-clarification-loop-memory-arbitration-design.md docs/superpowers/plans/2026-05-13-clarification-loop-memory-arbitration.md docs/dev-log/context-continuity-optimization.md
git commit -m "feat: 闭环澄清并仲裁记忆冲突"
```
