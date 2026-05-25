# Conversation Compact Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first phase of conversation compact context so long chats get a short-term, psychology-aware compact pack without polluting long-term memory.

**Architecture:** Add an independent `compact_context_service` that builds a transient `compact_context_pack` from recent messages, session digest, risk level, and runtime time policy. Pass that pack through `chat_service -> GraphRuntime -> AgentState`, then render it in `dialogue_prompt_builder` as executable guidance. Persist only lightweight debug metadata in assistant result/metadata; do not write compact data into `memory_candidates` or `UserMemory`.

**Tech Stack:** Python, FastAPI service layer, LangGraph `AgentState`, SQLAlchemy models already in place, pytest/unittest.

---

## File Structure

- Create: `backend/app/services/compact_context_service.py`
  - Pure functions for estimating context pressure, deciding compact triggers, building compact event/state/pack, and formatting safe short-term guidance.
- Create: `backend/tests/test_compact_context_service.py`
  - Unit tests for trigger decisions, stale anchor detection, risk filtering, time policy, and memory separation.
- Modify: `backend/app/graphs/state.py`
  - Add `compact_context_pack: dict`.
- Modify: `backend/app/services/graph_runtime.py`
  - Accept and pass `compact_context_pack` through non-stream and stream paths; include it in mapped result for metadata/trace visibility.
- Modify: `backend/app/services/chat_service.py`
  - Build compact pack in `_prepare_turn_context`; pass it to GraphRuntime; save compact metadata in assistant message metadata/result snapshot.
- Modify: `backend/app/services/dialogue_prompt_builder.py`
  - Render a compact context prompt block before long-term memory/digest blocks.
- Modify: `backend/tests/test_chat_idempotency.py`
  - Verify chat service builds and passes compact pack.
- Modify: `backend/tests/test_graph_runtime_streaming.py`
  - Verify runtime includes compact pack in input/mapped result and stream progress remains private.
- Modify: `backend/tests/test_dialogue_prompt_builder.py`
  - Verify compact block is injected, stale anchors are lowered, raw keys are not leaked, and compact remains present when user context pack exists.

## Task 1: Compact Context Service

**Files:**
- Create: `backend/app/services/compact_context_service.py`
- Create: `backend/tests/test_compact_context_service.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
from app.services.compact_context_service import (
    build_compact_context_pack,
    estimate_context_budget,
    should_compact_context,
)


def _msg(index: int, role: str, content: str, **metadata):
    return {
        "id": f"msg-{index}",
        "role": role,
        "content": content,
        "metadata": metadata,
        "risk_level": metadata.get("risk_level"),
        "created_at": f"2026-05-17T12:{index:02d}:00+08:00",
    }


def test_estimate_context_budget_uses_character_fallback():
    budget = estimate_context_budget([_msg(1, "user", "a" * 250)], max_chars=1000)
    assert budget["used_chars"] == 250
    assert budget["usage_ratio"] == 0.25


def test_should_compact_when_context_is_long_or_quality_warns():
    messages = [_msg(i, "user", f"消息 {i}") for i in range(14)]
    decision = should_compact_context(
        recent_messages=messages,
        quality_signals={"recent_repetition_risk": "high"},
        max_messages=10,
        max_chars=5000,
    )
    assert decision["should_compact"] is True
    assert "message_threshold" in decision["reasons"]
    assert "quality_repetition_risk" in decision["reasons"]


def test_build_pack_marks_old_anchor_as_stale_when_user_does_not_reuse_it():
    messages = [
        _msg(1, "user", "我刚才说在轮下那个感觉"),
        _msg(2, "assistant", "你提到了在轮下。"),
        _msg(3, "user", "其实现在就是很生气"),
        _msg(4, "assistant", "我听到的是生气。"),
        _msg(5, "user", "对，很堵。"),
    ]
    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={"summary_200chars": "用户早前提到在轮下，后来转向生气和堵。"},
        risk_level="L0",
        max_recent_messages=2,
    )
    assert pack["state"]["stale_threads"][0]["topic"] == "在轮下"
    assert "不要复用" in pack["state"]["stale_threads"][0]["reuse_policy"]
    assert "在轮下" in pack["event"]["summary"]


def test_build_pack_keeps_user_boundaries_and_time_policy_without_long_term_candidates():
    messages = [
        _msg(1, "user", "别一直分析我，也不要连着问。"),
        _msg(2, "assistant", "好，我会放慢。"),
    ]
    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={},
        risk_level="L0",
    )
    assert any("分析" in item for item in pack["state"]["user_boundaries"])
    assert pack["state"]["time_context_policy"]["timezone"] == "Asia/Wuhan"
    assert pack["memory_candidates"] == []


def test_high_risk_pack_filters_operational_details():
    messages = [
        _msg(1, "user", "我想用某个具体工具伤害自己"),
        _msg(2, "assistant", "先把那个东西放远一点。"),
    ]
    pack = build_compact_context_pack(
        recent_messages=messages,
        session_digest={},
        risk_level="L2",
    )
    assert pack["state"]["safety_context"]["risk_level"] == "L2"
    assert "具体工具" not in str(pack)
    assert "安全连续性" in pack["state"]["safety_context"]["note"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd backend
python -m pytest tests/test_compact_context_service.py -q
```

Expected: import failure for missing `app.services.compact_context_service`.

- [ ] **Step 3: Implement service**

Implement pure dict-based helpers:

- `estimate_context_budget(recent_messages, max_chars=6000) -> dict`
- `should_compact_context(recent_messages, quality_signals=None, max_messages=10, max_chars=6000, force=False) -> dict`
- `build_compact_context_pack(recent_messages, session_digest=None, risk_level="L0", quality_signals=None, max_recent_messages=10, now=None) -> dict`

The pack must include:

- `schema_version`
- `event`
- `state`
- `memory_candidates: []`
- `source: "runtime_compact_context"`

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd backend
python -m pytest tests/test_compact_context_service.py -q
```

Expected: all tests pass.

## Task 2: Runtime And Chat Integration

**Files:**
- Modify: `backend/app/graphs/state.py`
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/tests/test_chat_idempotency.py`
- Modify: `backend/tests/test_graph_runtime_streaming.py`

- [ ] **Step 1: Write failing tests**

Add runtime test:

```python
def test_graph_runtime_input_state_includes_compact_context_pack() -> None:
    runtime = object.__new__(GraphRuntime)
    pack = {"schema_version": 1, "state": {"summary_for_prompt": "短期状态"}}

    state = runtime._build_input_state(
        thread_id="thread-1",
        user_id="user-1",
        content="继续",
        compact_context_pack=pack,
    )

    assert state["compact_context_pack"] == pack
```

Add chat service test:

```python
def test_chat_turn_passes_compact_context_pack_to_graph_runtime(self) -> None:
    user = self.create_user()
    thread = self.create_thread(user)
    base_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    for index, content in enumerate(
        ["在轮下那个感觉", "我听到了这个锚点", "现在其实是很生气", "我不想一直讲那个词"]
    ):
        self.db.add(
            Message(
                thread_id=thread.id,
                user_id=user.id,
                role="user" if index % 2 == 0 else "assistant",
                content=content,
                input_type="text",
                created_at=base_time + timedelta(seconds=index),
            )
        )
    self.db.commit()
    fake_runtime = FakeGraphRuntime()
    chat_service.graph_runtime = fake_runtime

    response = self.client.post(
        f"/api/v1/chat/threads/{thread.id}/messages",
        headers=self.auth_headers(user),
        json={"client_message_id": "client-compact", "content": "我现在很生气"},
    )

    self.assertEqual(response.status_code, 200)
    pack = fake_runtime.calls[0]["compact_context_pack"]
    self.assertEqual(pack["schema_version"], 1)
    self.assertIn("state", pack)
    self.assertEqual(pack["memory_candidates"], [])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd backend
python -m pytest tests/test_chat_idempotency.py::ChatIdempotencyTests::test_chat_turn_passes_compact_context_pack_to_graph_runtime tests/test_chat_idempotency.py::ChatIdempotencyTests::test_graph_runtime_input_state_includes_compact_context_pack -q
```

Expected: missing argument/state failures.

- [ ] **Step 3: Implement integration**

Add `compact_context_pack` to:

- `AgentState`
- `TurnContext`
- `_prepare_turn_context()`
- `_invoke_graph_with_fallback()`
- both `graph_runtime.invoke_turn()` and `graph_runtime.stream_turn()` calls
- `GraphRuntime._build_input_state()`
- `GraphRuntime.invoke_turn()` and `GraphRuntime.stream_turn()` signatures
- `GraphRuntime._map_result()` output
- assistant metadata in `_persist_turn_result()`

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
cd backend
python -m pytest tests/test_chat_idempotency.py tests/test_graph_runtime_streaming.py -q
```

Expected: pass.

## Task 3: Prompt Injection

**Files:**
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Modify: `backend/tests/test_dialogue_prompt_builder.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_prompt_includes_compact_context_pack_before_memory_blocks(self) -> None:
    state = self.make_state(
        compact_context_pack={
            "schema_version": 1,
            "state": {
                "summary_for_prompt": "用户现在主要在表达生气和堵。",
                "active_threads": [{"topic": "当前生气", "next_move_hint": "先承接"}],
                "stale_threads": [{"topic": "在轮下", "reuse_policy": "除非用户主动提起，否则不要复用"}],
                "user_boundaries": ["用户不喜欢被强行分析"],
                "interaction_preferences": ["少连续追问"],
                "safety_context": {"risk_level": "L0"},
                "time_context_policy": {"timezone": "Asia/Wuhan", "source": "runtime"},
                "quality_signals": {"recent_repetition_risk": "high"},
            },
        }
    )
    parts = build_dialogue_prompt_parts(
        state,
        mode="companion",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )
    assert "当前会话压缩状态" in parts.user_prompt
    assert "用户现在主要在表达生气和堵" in parts.user_prompt
    assert "在轮下" in parts.user_prompt
    assert "不要复用" in parts.user_prompt
    assert "Asia/Wuhan" in parts.user_prompt
    assert "compact_context_pack" not in parts.user_prompt
    assert "schema_version" not in parts.user_prompt


def test_prompt_keeps_compact_context_when_user_context_pack_exists(self) -> None:
    state = self.make_state(
        compact_context_pack={"state": {"summary_for_prompt": "短期压缩状态"}},
        user_context_pack={"active_goal": "先把情绪稳住"},
        session_digest={"summary_200chars": "旧摘要"},
    )
    parts = build_dialogue_prompt_parts(
        state,
        mode="companion",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )
    assert "当前会话压缩状态" in parts.user_prompt
    assert "短期压缩状态" in parts.user_prompt
    assert "用户上下文优先级包" in parts.user_prompt
    assert "会话全景" not in parts.user_prompt
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd backend
python -m pytest tests/test_dialogue_prompt_builder.py -q
```

Expected: new compact prompt assertions fail.

- [ ] **Step 3: Implement prompt block**

Add `_compact_context_prompt_block(state)` and call it in `build_dialogue_prompt_parts()` before temporal/move/risk blocks or immediately after `response_contract`.

Rules:

- Render as behavior guidance, not raw JSON.
- Include summary, active threads, stale threads, boundaries, interaction preferences, risk level, time policy, and quality warnings when present.
- Do not expose raw keys like `schema_version`, `compact_id`, `forgotten_turn_ids`, or `compact_context_pack`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd backend
python -m pytest tests/test_dialogue_prompt_builder.py -q
```

Expected: pass.

## Task 4: Final Verification

**Files:**
- Review all modified backend files.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
cd backend
python -m pytest tests/test_compact_context_service.py tests/test_dialogue_prompt_builder.py tests/test_chat_idempotency.py tests/test_graph_runtime_streaming.py -q
```

Expected: pass.

- [ ] **Step 2: Run diff check**

Run:

```powershell
git diff --check -- backend/app/services/compact_context_service.py backend/app/services/dialogue_prompt_builder.py backend/app/services/graph_runtime.py backend/app/services/chat_service.py backend/app/graphs/state.py backend/tests/test_compact_context_service.py backend/tests/test_dialogue_prompt_builder.py backend/tests/test_chat_idempotency.py backend/tests/test_graph_runtime_streaming.py
```

Expected: no output.

- [ ] **Step 3: Commit**

Commit only compact-related tracked/new files:

```powershell
git add -- backend/app/services/compact_context_service.py backend/app/services/dialogue_prompt_builder.py backend/app/services/graph_runtime.py backend/app/services/chat_service.py backend/app/graphs/state.py backend/tests/test_compact_context_service.py backend/tests/test_dialogue_prompt_builder.py backend/tests/test_chat_idempotency.py backend/tests/test_graph_runtime_streaming.py docs/superpowers/plans/2026-05-17-conversation-compact-context.md
git commit -m "feat: 增加对话 compact 上下文"
```
