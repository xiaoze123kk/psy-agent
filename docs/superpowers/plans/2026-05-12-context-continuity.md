# 上下文连续性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让会话回复、记忆检索和摘要持久化使用稳定的会话全景，同时保留 `last_summary` 兼容。

**Architecture:** 新增 `session_digest` 作为会话级结构化状态，在 `GraphRuntime` 和 chat 持久化链路中透传。回复链路先通过多轮 messages 恢复真实对话上下文，记忆检索只消费 digest 中稳定的结构化字段。

**Tech Stack:** FastAPI, SQLAlchemy, LangGraph, pytest/unittest, DeepSeek chat client wrapper.

---

### Task 1: Add Session Digest State And Persistence

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/graphs/state.py`
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_idempotency.py`

- [x] **Step 1: Write the failing persistence test**

Add a test proving `session_digest` returned by the graph is persisted on `ConversationThread`, while `last_summary` still receives the short summary.

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_chat_idempotency.py::ChatIdempotencyTests::test_session_digest_persists_without_replacing_last_summary -q
```

Expected: fail because `ConversationThread.session_digest` does not exist.

- [x] **Step 3: Implement minimal persistence**

Add `session_digest` to the model, graph state, runtime input/output mapping, and chat persistence. Keep `last_summary` as `session_summary`.

- [x] **Step 4: Run test to verify it passes**

Run the same test command. Expected: pass.

### Task 2: Build Multi-Turn Reply Messages

**Files:**
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Modify: `backend/app/graphs/nodes/response_nodes.py`
- Modify: `backend/app/services/tooling.py`
- Test: `backend/tests/test_response_memory_continuity.py`

- [x] **Step 1: Write failing message-shape tests**

Add tests proving normal replies and tool replies pass recent user/assistant turns as real chat messages before the current user turn.

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py::ResponseMemoryContinuityTests::test_companion_reply_uses_multi_turn_messages tests/test_response_memory_continuity.py::ResponseMemoryContinuityTests::test_tool_reply_uses_multi_turn_messages -q
```

Expected: fail because reply calls still send only `[system, user]`.

- [x] **Step 3: Implement multi-turn message builder**

Create a helper that combines system prompt, bounded `recent_messages`, and current user prompt. Use the same messages in streamed and tool branches.

- [x] **Step 4: Run tests to verify they pass**

Run the same command. Expected: pass.

### Task 3: Make Memory Retrieval Session-Digest Aware

**Files:**
- Modify: `backend/app/services/memory_service.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_memory_service.py`

- [x] **Step 1: Write failing retrieval test**

Add a test proving `key_themes` from `session_digest` can make a relevant memory win when the current query is vague.

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py::MemoryServiceTests::test_retrieve_uses_session_digest_themes_for_vague_query -q
```

Expected: fail because retrieval query ignores `session_digest`.

- [x] **Step 3: Implement digest query extraction**

Accept optional `session_digest`, extract `key_themes`, `emotional_arc`, and `unresolved_threads`, and include only those fields in query text. Pass `thread.session_digest` from chat preparation.

- [x] **Step 4: Run test to verify it passes**

Run the same command. Expected: pass.

### Task 4: Update Logs And Run Focused Verification

**Files:**
- Modify: `docs/dev-log/context-continuity-optimization.md`

- [x] **Step 1: Update iteration log**

Record the implementation slices, tests, and remaining follow-up.

- [x] **Step 2: Run focused suite**

Run:

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py tests/test_memory_service.py tests/test_chat_idempotency.py -q
```

Expected: pass with only existing warnings.
