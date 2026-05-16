# 回复结尾策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让后端不再默认每轮以问题结尾，而是根据上下文动态选择问题、轻邀请、留白、微行动或自然收束。

**Architecture:** 在 `risk_response_policy` 中新增结尾策略字段，由 prompt builder 注入模型指令，再由 experience validator 检查连续追问、无必要问题收尾和重复安全问题。质量 eval 增加“连续追问感”用例，防止回归。

**Tech Stack:** Python, FastAPI backend, LangGraph node state, unittest/pytest, JSON eval fixtures.

---

## Files And Ownership

- Worker A owns `backend/app/services/risk_policy.py` and `backend/tests/test_risk_policy.py`.
- Worker B owns `backend/app/services/dialogue_prompt_builder.py` and `backend/tests/test_dialogue_prompt_builder.py`.
- Worker C owns `backend/app/graphs/nodes/validator_nodes.py` and `backend/tests/test_conversation_control_rag.py`.
- Worker D owns `backend/tests/evals/test_conversation_quality.py` and `backend/tests/evals/fixtures_conversation_quality.json`.
- Controller owns this plan, integration review, final test runs, and final commit.

## Task 1: Risk Policy Ending Fields

**Files:**
- Modify: `backend/app/services/risk_policy.py`
- Test: `backend/tests/test_risk_policy.py`

- [x] **Step 1: Write failing tests**

Add tests proving:

```python
def test_normal_support_after_question_streak_uses_no_question_budget(self) -> None:
    policy = build_risk_response_policy(
        {
            "risk_level": "L0",
            "control_category": "normal_support",
            "normalized_text": "在轮下，记得吗",
            "recent_messages": [
                {"role": "assistant", "content": "你是想聊这本书吗？"},
                {"role": "user", "content": "记得"},
            ],
        }
    )

    self.assertEqual(policy["ending_style"], "reflective_pause")
    self.assertEqual(policy["question_budget"], 0)
    self.assertEqual(policy["avoid_question_reason"], "previous_turn_ended_with_question")


def test_l3_first_contact_allows_immediate_safety_question(self) -> None:
    policy = build_risk_response_policy(
        {
            "risk_level": "L3",
            "control_category": "self_harm_risk",
            "semantic_risk": {"means": True, "timeframe": "near_term"},
            "normalized_text": "我现在不想活了，那个东西就在手边",
            "recent_messages": [],
        }
    )

    self.assertEqual(policy["ending_style"], "micro_step")
    self.assertEqual(policy["question_budget"], 1)
    self.assertEqual(policy["allow_question_reason"], "immediate_safety_check")


def test_deescalating_safety_answer_stops_repeated_safety_question(self) -> None:
    policy = build_risk_response_policy(
        {
            "risk_level": "L2",
            "control_category": "self_harm_risk",
            "semantic_risk": {"protective_factor": True},
            "normalized_text": "我现在安全，没有计划",
            "recent_messages": [
                {"role": "assistant", "content": "你现在安全吗？"},
                {"role": "user", "content": "我现在安全，没有计划"},
            ],
        }
    )

    self.assertEqual(policy["ending_style"], "micro_step")
    self.assertEqual(policy["question_budget"], 0)
    self.assertEqual(policy["avoid_question_reason"], "safety_answer_already_given")
```

- [x] **Step 2: Verify red**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_risk_policy.py -q
```

Expected: fail because `ending_style`, `question_budget`, and reason fields do not exist.

- [x] **Step 3: Implement minimal policy helpers**

Add helpers that inspect `recent_messages`, current risk level, risk domain, and safety-answer signals. Return fields:

```python
{
    "ending_style": "...",
    "question_budget": 0,
    "avoid_question_reason": "...",
    "allow_question_reason": "...",
    "question_ending_streak": 1,
    "last_turn_had_safety_question": True,
    "user_answered_previous_question": True,
}
```

Keep `max_questions: 1` for backward compatibility.

- [x] **Step 4: Verify green**

Run the same pytest command. Expected: all `test_risk_policy.py` tests pass.

## Task 2: Prompt Injection For Ending Strategy

**Files:**
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_dialogue_prompt_builder.py`

- [x] **Step 1: Write failing tests**

Add tests proving the prompt says questions are optional and follows `question_budget=0`:

```python
def test_prompt_injects_no_question_ending_strategy(self) -> None:
    parts = build_dialogue_prompt_parts(
        self.make_state(
            risk_response_policy={
                "ending_style": "reflective_pause",
                "question_budget": 0,
                "avoid_question_reason": "previous_turn_ended_with_question",
                "question_ending_streak": 1,
            }
        ),
        mode="companion",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )

    self.assertIn("结尾策略", parts.user_prompt)
    self.assertIn("reflective_pause", parts.user_prompt)
    self.assertIn("question_budget=0", parts.user_prompt)
    self.assertIn("不要用问句收尾", parts.user_prompt)
    self.assertIn("问题是可选动作", parts.user_prompt)


def test_prompt_injects_micro_step_strategy_for_crisis(self) -> None:
    parts = build_dialogue_prompt_parts(
        self.make_state(
            risk_level="L3",
            route_priority="P0_immediate_safety",
            risk_response_policy={
                "ending_style": "micro_step",
                "question_budget": 1,
                "allow_question_reason": "immediate_safety_check",
            },
        ),
        mode="crisis",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )

    self.assertIn("micro_step", parts.user_prompt)
    self.assertIn("只给一个低门槛动作", parts.user_prompt)
```

- [x] **Step 2: Verify red**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_dialogue_prompt_builder.py -q
```

Expected: fail because the new prompt block is absent.

- [x] **Step 3: Implement prompt block**

Add `_response_ending_prompt_block(state)` that reads `risk_response_policy` and emits an internal block. Insert it into `user_prompt` near the risk semantic and turn-priority blocks.

Core language:

```text
结尾策略（内部使用，不要暴露字段名）：
- 问题是可选动作，不是默认结尾；“最多一个问题”表示上限，不表示必须提问。
- 本轮 ending_style=...
- 本轮 question_budget=...
- 当 question_budget=0 时，不要用问句收尾；优先使用陈述留白、轻邀请、总结停顿或自然收束。
```

- [x] **Step 4: Verify green**

Run the same pytest command. Expected: all `test_dialogue_prompt_builder.py` tests pass.

## Task 3: Experience Validator For Question Endings

**Files:**
- Modify: `backend/app/graphs/nodes/validator_nodes.py`
- Test: `backend/tests/test_conversation_control_rag.py`

- [x] **Step 1: Write failing tests**

Add tests for:

```python
def test_validator_warns_when_question_budget_zero_ends_with_question(self) -> None:
    state = self.make_state(
        "在轮下，记得吗",
        risk_level="L0",
        risk_response_policy={
            "ending_style": "reflective_pause",
            "question_budget": 0,
            "question_ending_streak": 1,
        },
        assistant_text="《在轮下》那种被推着走的窒息感确实贴近你刚才说的处境。你是觉得自己也被什么东西一直往下压吗？",
        suggested_actions=[],
    )

    result = _run(response_validator(state))

    self.assertIn("unnecessary_question_ending", result["experience_validator_reasons"])
    self.assertIn("question_streak", result["experience_validator_reasons"])
    self.assertEqual(result["validator_severity"], "warning")


def test_validator_blocks_repeated_safety_question_after_answer(self) -> None:
    state = self.make_state(
        "我现在安全，没有计划",
        risk_level="L2",
        route_priority="P0_immediate_safety",
        control_category="self_harm_risk",
        risk_response_policy={
            "risk_domain": "self_harm",
            "risk_phase": "deescalating",
            "ending_style": "micro_step",
            "question_budget": 0,
            "avoid_question_reason": "safety_answer_already_given",
            "last_turn_had_safety_question": True,
            "char_budget": {"target": 220, "max": 360},
        },
        assistant_text="我听到了。你现在安全吗？身边有人吗？",
        suggested_actions=[],
    )
    model_reply = "好，先不继续盘问安全问题了。我们只把这一分钟放慢一点，你回我一个字也可以。\\n---\\n我还在\\n先慢一点\\n继续陪我"

    with patch("app.graphs.nodes.validator_nodes.deepseek_client.chat", new=AsyncMock(return_value=model_reply)):
        result = _run(response_validator(state))

    self.assertTrue(result["validator_blocked"])
    self.assertIn("repeated_safety_question", result["experience_validator_reasons"])
    self.assertEqual(result["delivery_status"], "generated")
```

- [x] **Step 2: Verify red**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_control_rag.py -q
```

Expected: fail because new validator reasons do not exist.

- [x] **Step 3: Implement validator logic**

Add helpers:

```python
QUESTION_MARKS = ("\uff1f", "?")

def _question_count(text: str) -> int:
    return sum(text.count(mark) for mark in QUESTION_MARKS)

def _ends_with_question(text: str) -> bool:
    return text.rstrip().endswith(QUESTION_MARKS)
```

Use `question_budget` when present, else `max_questions`. Add reasons:

- `unnecessary_question_ending`: `question_budget == 0` and assistant text ends with a question.
- `question_streak`: `question_ending_streak >= 1`, risk is L0/L1, and assistant text ends with a question.
- `repeated_safety_question`: `avoid_question_reason == "safety_answer_already_given"` and assistant asks safety questions again.

Severity:

- `unnecessary_question_ending` and `question_streak` are warnings.
- `repeated_safety_question` is blocking so safety-path regeneration can repair it.
- Keep existing `too_many_questions` warning behavior.

- [x] **Step 4: Verify green**

Run the same pytest command. Expected: all `test_conversation_control_rag.py` tests pass.

## Task 4: Conversation Quality Eval

**Files:**
- Modify: `backend/tests/evals/test_conversation_quality.py`
- Modify: `backend/tests/evals/fixtures_conversation_quality.json`

- [x] **Step 1: Write failing eval assertions**

Add eval support:

```python
def ends_with_question(text: str) -> bool:
    return text.rstrip().endswith(("\uff1f", "?"))
```

In `quality_report`, when a fixture has `must` containing `no_question_ending`, append `unnecessary_question_ending` if `ends_with_question(text)`.

- [x] **Step 2: Add fixture**

Add a case for the screenshot pattern:

```json
{
  "id": "literary_reflection_no_default_question_ending",
  "category": "ending_style",
  "user_mode": "adult",
  "intent": "vent",
  "user_text": "我感叹的是现在的高中和社会就像是在轮下，什么时候都在奔跑，不然就会被碾死在轮下",
  "recent_messages": [
    {"role": "assistant", "content": "你提到《在轮下》，是因为今天被雨淋湿的感觉，让你想起他书里的什么东西了吗？"},
    {"role": "user", "content": "在轮下，记得吗"},
    {"role": "assistant", "content": "你是觉得今天就像汉斯那样，被什么东西一直往下压吗？"}
  ],
  "retrieved_memories": [],
  "retrieved_counseling_examples": [],
  "positive_response": "《在轮下》那种被推着往前走的窒息感，确实很贴近你说的处境。你说“不然就会被碾死”，听起来不是夸张，而是那种一直被现实追着跑、没有喘息口的感觉。这句话先不用急着解释，它已经把那种压力说出来了。",
  "negative_response": "《在轮下》那种窒息感和你现在很像。你最近是哪件事让这种感觉最深？",
  "must": ["empathic_reflection", "anchor_user_words", "max_one_question", "no_question_ending"],
  "must_not": [],
  "anchors": ["在轮下", "奔跑", "碾死"],
  "min_score": 0.85,
  "expected_negative_failures": ["unnecessary_question_ending"]
}
```

- [x] **Step 3: Verify red/green**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/evals/test_conversation_quality.py -q
```

Expected after implementation: pass, with the negative fixture reporting `unnecessary_question_ending`.

## Integration Verification

- [x] Run targeted tests:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_risk_policy.py tests/test_dialogue_prompt_builder.py tests/test_conversation_control_rag.py tests/evals/test_conversation_quality.py -q
```

- [x] Run broader safe regression:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_safety_evaluation.py tests/test_conversation_control_rag.py tests/test_risk_policy.py tests/test_dialogue_prompt_builder.py -q
```

- [x] Run whitespace check:

```powershell
git diff --check
```

## Commit

After tests pass, commit only related files:

```powershell
git add docs/superpowers/plans/2026-05-16-response-ending-style.md backend/app/services/risk_policy.py backend/tests/test_risk_policy.py backend/app/services/dialogue_prompt_builder.py backend/tests/test_dialogue_prompt_builder.py backend/app/graphs/nodes/validator_nodes.py backend/tests/test_conversation_control_rag.py backend/tests/evals/test_conversation_quality.py backend/tests/evals/fixtures_conversation_quality.json
git commit -m "feat: 优化回复结尾策略"
```
