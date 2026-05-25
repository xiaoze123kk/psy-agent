# User Context Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and inject a prioritized `user_context_pack` so response prompts use one coherent user-understanding context.

**Architecture:** Add a focused service that composes existing `session_digest`, `user_profile_digest`, `goal_state`, and retrieved memories into a compact dict. Pass that dict through chat context and graph state, then make the prompt builder prefer it over older separated blocks.

**Tech Stack:** Python, FastAPI service layer, LangGraph state, pytest/unittest.

---

### Task 1: Add Context Pack Service

**Files:**
- Create: `backend/app/services/user_context_pack_service.py`
- Test: `backend/tests/test_user_context_pack_service.py`

- [ ] **Step 1: Write failing service tests**

Create tests for `build_user_context_pack()`:
- combines `goal_state.clarification_answer`, `goal_state.current_goal`, `session_digest.summary_200chars`, `user_profile_digest.correction_hints`, and retrieved memories;
- truncates list fields;
- strips ordinary profile/retrieved memory context for `risk_level="L2"`.

- [ ] **Step 2: Run service tests red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_user_context_pack_service.py -q
```

Expected: import failure because the service does not exist.

- [ ] **Step 3: Implement service**

Create `build_user_context_pack()` with deterministic compaction helpers and no database dependency.

- [ ] **Step 4: Run service tests green**

Run the same command and expect all tests to pass.

### Task 2: Thread Pack Through Runtime

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/graphs/state.py`
- Modify: `backend/app/graphs/nodes/input_nodes.py`
- Test: `backend/tests/test_memory.py`
- Test: `backend/tests/test_chat_idempotency.py`

- [ ] **Step 1: Write failing integration tests**

Add tests proving `process_message_turn()` passes `user_context_pack` to fake runtime and `GraphRuntime._build_input_state()` includes it.

- [ ] **Step 2: Run integration tests red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py::ChatMemoryModeTests::test_long_term_turn_passes_user_context_pack_to_runtime tests/test_chat_idempotency.py::ChatIdempotencyTests::test_graph_runtime_input_state_includes_user_context_pack -q
```

Expected: fail because `user_context_pack` is not built or accepted.

- [ ] **Step 3: Implement runtime plumbing**

Extend `TurnContext`, `GraphRuntime` signatures, state, and input nodes.

- [ ] **Step 4: Run integration tests green**

Run the same command and expect both tests to pass.

### Task 3: Prompt Builder Prefers Pack

**Files:**
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_dialogue_prompt_builder.py`

- [ ] **Step 1: Write failing prompt test**

Add a test where `user_context_pack` exists and prompt includes “用户上下文优先级包” while omitting old duplicate “会话全景” and “用户画像” blocks.

- [ ] **Step 2: Run prompt test red**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_dialogue_prompt_builder.py::DialoguePromptBuilderTests::test_prompt_prefers_user_context_pack_over_separate_blocks -q
```

Expected: fail because prompt builder ignores the pack.

- [ ] **Step 3: Implement prompt block**

Add `_user_context_pack_prompt_block()` and branch so legacy blocks are only included when pack is empty.

- [ ] **Step 4: Run prompt test green**

Run the same command and expect it to pass.

### Task 4: Log, Regression, Commit

**Files:**
- Modify: `docs/dev-log/context-continuity-optimization.md`

- [ ] **Step 1: Update iteration log**

Add “统一用户上下文打包器” with implementation points and red/green/regression results.

- [ ] **Step 2: Run focused regression**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_user_context_pack_service.py tests/test_user_context_service.py tests/test_dialogue_prompt_builder.py tests/test_memory.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_memory_service.py tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Commit**

Stage only this feature's files and commit:

```powershell
git add backend/app/services/user_context_pack_service.py backend/app/services/chat_service.py backend/app/services/graph_runtime.py backend/app/graphs/state.py backend/app/graphs/nodes/input_nodes.py backend/app/services/dialogue_prompt_builder.py backend/tests/test_user_context_pack_service.py backend/tests/test_memory.py backend/tests/test_chat_idempotency.py backend/tests/test_dialogue_prompt_builder.py docs/dev-log/context-continuity-optimization.md docs/superpowers/specs/2026-05-13-user-context-pack-design.md docs/superpowers/plans/2026-05-13-user-context-pack.md
git commit -m "feat: 统一打包用户上下文"
```
