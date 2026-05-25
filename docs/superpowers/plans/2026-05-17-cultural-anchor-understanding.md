# Cultural Anchor Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement structured cultural anchor evidence so the agent can respond to books, people, concepts, quotes, and vague cultural references using user-provided clues without fabricating details.

**Architecture:** Extend the existing `conversation_move_policy` dict with backward-compatible `anchor_evidence` and `cultural_response_mode` fields. Prompt builder will summarize those fields as actionable guidance, validator will use them to flag overconfident or shallow cultural replies, and eval fixtures will cover positive/negative examples.

**Tech Stack:** Python, FastAPI/LangGraph backend, pytest, existing conversation quality eval fixtures.

---

## File Structure

- `backend/app/services/conversation_move_policy.py`
  - Owns cultural anchor extraction and `anchor_evidence` construction.
  - Must preserve existing `topic_anchor`, `anchor_value`, and `anchor_handling` fields.
- `backend/app/services/dialogue_prompt_builder.py`
  - Converts `anchor_evidence` into compact internal prompt guidance.
- `backend/app/graphs/nodes/validator_nodes.py`
  - Adds cultural quality reasons using `anchor_evidence`.
- `backend/tests/test_conversation_move_policy.py`
  - Unit tests for anchor evidence extraction and compatibility.
- `backend/tests/test_dialogue_prompt_builder.py`
  - Prompt tests for evidence summary and hidden JSON fields.
- `backend/tests/test_conversation_control_rag.py`
  - Validator tests for overconfident, shallow, missed-clue, and non-fabricated cases.
- `backend/tests/evals/fixtures_conversation_quality.json`
  - Adds cultural anchor scenarios.
- `backend/tests/evals/test_conversation_quality.py`
  - Adds scoring hooks for new cultural failures.

Existing dirty changes in `conversation_move_policy.py`, `validator_nodes.py`, and `test_conversation_move_policy.py` generalize cultural anchor detection. Preserve those changes and build on top of them.

---

### Task 1: Anchor Evidence Extraction

**Files:**
- Modify: `backend/app/services/conversation_move_policy.py`
- Test: `backend/tests/test_conversation_move_policy.py`

- [ ] **Step 1: Write failing tests for `anchor_evidence`**

Add tests to `ConversationMovePolicyTests`:

```python
def test_cultural_anchor_evidence_tracks_user_clues_and_forbidden_claims(self) -> None:
    policy = build_conversation_move_policy(
        {
            "user_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
            "normalized_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
            "risk_level": "L0",
            "recent_messages": [],
        }
    )

    evidence = policy["anchor_evidence"]

    self.assertEqual(policy["topic_anchor"], "literary")
    self.assertEqual(policy["anchor_value"], "德米安")
    self.assertEqual(evidence["anchor_type"], "literary")
    self.assertEqual(evidence["anchor_value"], "德米安")
    self.assertEqual(evidence["confidence"], "explicit")
    self.assertIn("user_clues", evidence)
    self.assertTrue(any(clue["text"] == "没读过" and clue["kind"] == "knowledge_boundary" for clue in evidence["user_clues"]))
    self.assertTrue(any(clue["text"] == "自我寻找" and clue["kind"] == "theme" for clue in evidence["user_clues"]))
    self.assertEqual(evidence["response_mode"], "echo_user_clue")
    self.assertIn("plot_detail", evidence["forbidden_claims"])
    self.assertIn("author_intent", evidence["forbidden_claims"])


def test_cultural_anchor_evidence_uses_no_knowledge_claim_for_uncertain_reference(self) -> None:
    policy = build_conversation_move_policy(
        {
            "user_text": "我记不清原句了，大概是说人一直被什么东西推着走",
            "normalized_text": "我记不清原句了，大概是说人一直被什么东西推着走",
            "risk_level": "L0",
            "recent_messages": [],
        }
    )

    evidence = policy["anchor_evidence"]

    self.assertEqual(evidence["anchor_type"], "quote")
    self.assertEqual(evidence["response_mode"], "no_knowledge_claim")
    self.assertTrue(any(clue["text"] == "记不清原句" for clue in evidence["user_clues"]))
    self.assertTrue(any(clue["text"] == "被什么东西推着走" for clue in evidence["user_clues"]))


def test_person_anchor_without_clues_asks_user_association(self) -> None:
    policy = build_conversation_move_policy(
        {
            "user_text": "你觉得林秋白是个什么样的人",
            "normalized_text": "你觉得林秋白是个什么样的人",
            "risk_level": "L0",
            "recent_messages": [],
        }
    )

    evidence = policy["anchor_evidence"]

    self.assertEqual(policy["topic_anchor"], "person")
    self.assertEqual(evidence["anchor_value"], "林秋白")
    self.assertEqual(evidence["response_mode"], "ask_user_association")
    self.assertIn("user_clues", evidence)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversation_move_policy.py -q
```

Expected: the three new tests fail because `anchor_evidence` is missing or incomplete.

- [ ] **Step 3: Implement anchor evidence helpers**

In `conversation_move_policy.py`, add helpers:

```python
CULTURAL_ANCHOR_TYPES = {"literary", "philosophical", "media", "person", "quote", "concept", "unknown_cultural"}
KNOWLEDGE_BOUNDARY_TERMS = ("没读过", "没看过", "只是听说", "听别人说", "不确定", "记不清", "不知道准不准")
THEME_CLUE_TERMS = ("自我寻找", "找自己", "阴影", "梦", "象征", "意义", "被规训", "被推着走", "慢半拍")


def _anchor_clue(text: str, kind: str, source: str = "current_user") -> dict[str, str]:
    return {"text": text, "kind": kind, "source": source}


def _user_clues_for_anchor(text: str) -> list[dict[str, str]]:
    clues: list[dict[str, str]] = []
    for term in KNOWLEDGE_BOUNDARY_TERMS:
        if term in text:
            clues.append(_anchor_clue(term, "knowledge_boundary"))
    for term in THEME_CLUE_TERMS:
        if term in text:
            clues.append(_anchor_clue(term, "theme"))
    quote_match = re.search(r"(记不清原句|原句记不清).{0,24}(推着走|一直被.{0,8}推着|被什么东西推着走)", text)
    if quote_match:
        clues.append(_anchor_clue("记不清原句", "knowledge_boundary"))
        clues.append(_anchor_clue("被什么东西推着走", "image"))
    return _dedupe_clues(clues)


def _dedupe_clues(clues: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for clue in clues:
        text = str(clue.get("text") or "").strip()
        kind = str(clue.get("kind") or "").strip()
        source = str(clue.get("source") or "current_user").strip()
        key = (text, kind)
        if not text or not kind or key in seen:
            continue
        seen.add(key)
        result.append({"text": text, "kind": kind, "source": source})
    return result
```

Add mode selection:

```python
def _cultural_response_mode(anchor_type: str, anchor_value: str, clues: Sequence[Mapping[str, str]], text: str) -> str:
    if anchor_type not in CULTURAL_ANCHOR_TYPES:
        return ""
    clue_kinds = {str(clue.get("kind") or "") for clue in clues}
    if "knowledge_boundary" in clue_kinds and anchor_type in {"quote", "unknown_cultural"}:
        return "no_knowledge_claim"
    if "knowledge_boundary" in clue_kinds or "theme" in clue_kinds or "image" in clue_kinds:
        return "echo_user_clue"
    if anchor_type in {"person", "concept"} and anchor_value:
        return "ask_user_association"
    if anchor_type in {"philosophical", "literary", "media"} and anchor_value:
        return "light_context_only"
    return "ask_user_association"
```

Add evidence builder:

```python
def _anchor_evidence(text: str, anchor_type: str, anchor_value: str, messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if anchor_type == "none" and not anchor_value:
        return {}
    effective_type = anchor_type
    if "记不清原句" in text or "原句记不清" in text:
        effective_type = "quote"
    if effective_type == "none" and _has_any(text, KNOWLEDGE_BOUNDARY_TERMS):
        effective_type = "unknown_cultural"

    clues = _user_clues_for_anchor(text)
    recent_context_clues = [
        _anchor_clue(title, "recent_title", "recent_context")
        for title in _recent_quoted_titles(messages)
        if title and title != anchor_value
    ][:3]
    confidence = "explicit" if anchor_value or clues else "weak"
    mode = _cultural_response_mode(effective_type, anchor_value, clues, text)

    forbidden_claims = ["plot_detail", "character_detail", "author_intent", "ending", "quote_attribution"]
    return {
        "anchor_type": effective_type,
        "anchor_value": anchor_value,
        "surface_text": text,
        "confidence": confidence,
        "user_clues": clues,
        "recent_context_clues": recent_context_clues,
        "allowed_basis": ["user_clues", "recent_context"],
        "forbidden_claims": forbidden_claims,
        "response_mode": mode,
    }
```

In `build_conversation_move_policy`, compute `anchor_evidence = _anchor_evidence(text, anchor_type, anchor_value, messages)` and include it in the returned dict. Also include `"cultural_response_mode": anchor_evidence.get("response_mode", "")`.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversation_move_policy.py -q
```

Expected: all tests in `test_conversation_move_policy.py` pass.

---

### Task 2: Prompt Guidance From Anchor Evidence

**Files:**
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_dialogue_prompt_builder.py`

- [ ] **Step 1: Write failing prompt tests**

Add tests:

```python
def test_prompt_includes_anchor_evidence_without_raw_json(self) -> None:
    state = self.make_state(
        normalized_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
        user_text="我没读过《德米安》，只是听别人说它和自我寻找有关",
        conversation_move_policy={
            "conversation_move": "respond_to_anchor",
            "topic_anchor": "literary",
            "anchor_value": "德米安",
            "anchor_evidence": {
                "anchor_type": "literary",
                "anchor_value": "德米安",
                "surface_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
                "confidence": "explicit",
                "user_clues": [
                    {"text": "没读过", "kind": "knowledge_boundary", "source": "current_user"},
                    {"text": "自我寻找", "kind": "theme", "source": "current_user"},
                ],
                "allowed_basis": ["user_clues", "recent_context"],
                "forbidden_claims": ["plot_detail", "character_detail", "author_intent", "ending"],
                "response_mode": "echo_user_clue",
            },
        },
    )

    parts = build_dialogue_prompt_parts(
        state,
        mode="companion",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )

    self.assertIn("文化锚点证据", parts.user_prompt)
    self.assertIn("德米安", parts.user_prompt)
    self.assertIn("没读过", parts.user_prompt)
    self.assertIn("自我寻找", parts.user_prompt)
    self.assertIn("不要百科介绍", parts.user_prompt)
    self.assertIn("禁止声称", parts.user_prompt)
    self.assertNotIn("anchor_evidence", parts.user_prompt)
    self.assertNotIn("user_clues", parts.user_prompt)


def test_prompt_guides_no_knowledge_claim_for_uncertain_quote(self) -> None:
    state = self.make_state(
        normalized_text="我记不清原句了，大概是说人一直被什么东西推着走",
        user_text="我记不清原句了，大概是说人一直被什么东西推着走",
        conversation_move_policy={
            "conversation_move": "respond_to_anchor",
            "topic_anchor": "quote",
            "anchor_value": "",
            "anchor_evidence": {
                "anchor_type": "quote",
                "anchor_value": "",
                "surface_text": "我记不清原句了，大概是说人一直被什么东西推着走",
                "confidence": "weak",
                "user_clues": [
                    {"text": "记不清原句", "kind": "knowledge_boundary", "source": "current_user"},
                    {"text": "被什么东西推着走", "kind": "image", "source": "current_user"},
                ],
                "allowed_basis": ["user_clues", "recent_context"],
                "forbidden_claims": ["quote_attribution", "author_intent"],
                "response_mode": "no_knowledge_claim",
            },
        },
    )

    parts = build_dialogue_prompt_parts(
        state,
        mode="companion",
        response_contract={"allow_rag": False},
        examples_text="",
        memory_text="",
    )

    self.assertIn("不要追出处", parts.user_prompt)
    self.assertIn("不要硬猜作者或原句", parts.user_prompt)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dialogue_prompt_builder.py -q
```

Expected: new tests fail because prompt does not summarize `anchor_evidence`.

- [ ] **Step 3: Implement prompt formatting**

In `dialogue_prompt_builder.py`, add helpers near `_conversation_move_policy_prompt_block`:

```python
_FORBIDDEN_CLAIM_LABELS = {
    "plot_detail": "具体情节",
    "character_detail": "角色细节",
    "author_intent": "作者意图",
    "ending": "结局",
    "quote_attribution": "原文出处",
}


def _compact_anchor_clues(raw_clues: object) -> list[str]:
    if not isinstance(raw_clues, list):
        return []
    clues: list[str] = []
    for clue in raw_clues[:5]:
        if not isinstance(clue, dict):
            continue
        text = _compact_text(clue.get("text"), limit=32)
        kind = _compact_text(clue.get("kind"), limit=32)
        if text and kind:
            clues.append(f"{text}（{kind}）")
    return clues


def _forbidden_claim_labels(raw_claims: object) -> list[str]:
    if not isinstance(raw_claims, list):
        return []
    labels: list[str] = []
    for claim in raw_claims[:6]:
        key = str(claim or "")
        labels.append(_FORBIDDEN_CLAIM_LABELS.get(key, key))
    return [label for label in labels if label]
```

In `_conversation_move_policy_prompt_block`, after the current `用户锚点` block, add:

```python
    evidence = policy.get("anchor_evidence")
    if isinstance(evidence, dict) and evidence:
        evidence_anchor_type = _compact_text(evidence.get("anchor_type"), limit=40)
        evidence_anchor_value = _compact_text(evidence.get("anchor_value"), limit=60)
        response_mode = _compact_text(evidence.get("response_mode"), limit=40)
        clues = _compact_anchor_clues(evidence.get("user_clues"))
        forbidden_claims = _forbidden_claim_labels(evidence.get("forbidden_claims"))
        anchor_label = evidence_anchor_type
        if evidence_anchor_value:
            anchor_label = f"{anchor_label} / {evidence_anchor_value}" if anchor_label else evidence_anchor_value
        if anchor_label or clues or response_mode:
            lines.append("文化锚点证据：")
        if anchor_label:
            lines.append(f"- 锚点：{anchor_label}")
        if clues:
            lines.append(f"- 用户给出的线索：{'、'.join(clues)}")
        if response_mode:
            lines.append(f"- 回应模式：{response_mode}")
        if forbidden_claims:
            lines.append(f"- 禁止声称：{'、'.join(forbidden_claims)}")
        if response_mode == "echo_user_clue":
            lines.append("- 写法：不要百科介绍；先顺着用户给出的线索聊，不补作品情节或作者观点。")
        elif response_mode == "ask_user_association":
            lines.append("- 写法：不要先做人物或作品简介；轻轻问用户为什么此刻想到这个锚点。")
        elif response_mode == "light_context_only":
            lines.append("- 写法：只给轻常识，马上回到用户为什么想聊它，不展开讲座。")
        elif response_mode == "no_knowledge_claim":
            lines.append("- 写法：不要追出处，不要硬猜作者或原句；只回应用户给出的画面或主题。")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dialogue_prompt_builder.py -q
```

Expected: all prompt builder tests pass.

---

### Task 3: Validator Cultural Quality Reasons

**Files:**
- Modify: `backend/app/graphs/nodes/validator_nodes.py`
- Test: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Write failing validator tests**

Add tests:

```python
def test_experience_validator_flags_overconfident_cultural_claim_when_user_is_uncertain(self) -> None:
    state = self.make_state(
        "我没读过《德米安》，只是听别人说它和自我寻找有关",
        risk_level="L0",
        conversation_move_policy={
            "conversation_move": "respond_to_anchor",
            "topic_anchor": "literary",
            "anchor_value": "德米安",
            "anchor_evidence": {
                "anchor_type": "literary",
                "anchor_value": "德米安",
                "user_clues": [
                    {"text": "没读过", "kind": "knowledge_boundary", "source": "current_user"},
                    {"text": "自我寻找", "kind": "theme", "source": "current_user"},
                ],
                "forbidden_claims": ["plot_detail", "character_detail", "author_intent", "ending"],
                "response_mode": "echo_user_clue",
            },
        },
    )

    reasons = experience_validator_reasons(
        "《德米安》主角最后明白自我寻找就是摆脱所有关系，所以你也该这样。",
        [],
        state,
    )

    self.assertIn("fabricated_cultural_claim", reasons)
    self.assertIn("overconfident_cultural_claim", reasons)


def test_experience_validator_flags_shallow_anchor_echo_when_user_clue_missing(self) -> None:
    state = self.make_state(
        "我没读过《德米安》，只是听别人说它和自我寻找有关",
        risk_level="L0",
        conversation_move_policy={
            "conversation_move": "respond_to_anchor",
            "topic_anchor": "literary",
            "anchor_value": "德米安",
            "anchor_evidence": {
                "anchor_type": "literary",
                "anchor_value": "德米安",
                "user_clues": [{"text": "自我寻找", "kind": "theme", "source": "current_user"}],
                "response_mode": "echo_user_clue",
            },
        },
    )

    reasons = experience_validator_reasons("《德米安》这个名字听起来确实挺重的。", [], state)

    self.assertIn("shallow_anchor_echo", reasons)
    self.assertIn("missed_user_cultural_clue", reasons)


def test_experience_validator_allows_user_clue_only_cultural_response(self) -> None:
    state = self.make_state(
        "我没读过《德米安》，只是听别人说它和自我寻找有关",
        risk_level="L0",
        conversation_move_policy={
            "conversation_move": "respond_to_anchor",
            "topic_anchor": "literary",
            "anchor_value": "德米安",
            "anchor_evidence": {
                "anchor_type": "literary",
                "anchor_value": "德米安",
                "user_clues": [
                    {"text": "没读过", "kind": "knowledge_boundary", "source": "current_user"},
                    {"text": "自我寻找", "kind": "theme", "source": "current_user"},
                ],
                "forbidden_claims": ["plot_detail", "character_detail", "author_intent", "ending"],
                "response_mode": "echo_user_clue",
            },
        },
    )

    reasons = experience_validator_reasons(
        "那我们先不假装已经知道很多，只抓住你给出的这条线索：《德米安》和“自我寻找”放在一起，像是在问一个人怎么慢慢分辨什么是自己的声音。",
        [],
        state,
    )

    self.assertNotIn("fabricated_cultural_claim", reasons)
    self.assertNotIn("overconfident_cultural_claim", reasons)
    self.assertNotIn("shallow_anchor_echo", reasons)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversation_control_rag.py -q
```

Expected: new tests fail because the new reasons are missing.

- [ ] **Step 3: Implement validator helpers**

In `validator_nodes.py`, add severity entries:

```python
    "overconfident_cultural_claim": "warning",
    "shallow_anchor_echo": "warning",
    "missed_user_cultural_clue": "warning",
```

Add helpers:

```python
def _anchor_evidence(policy: dict) -> dict:
    evidence = policy.get("anchor_evidence")
    return dict(evidence) if isinstance(evidence, dict) else {}


def _evidence_user_clues(evidence: dict) -> list[str]:
    clues = evidence.get("user_clues")
    if not isinstance(clues, list):
        return []
    values: list[str] = []
    for clue in clues:
        if not isinstance(clue, dict):
            continue
        text = str(clue.get("text") or "").strip()
        kind = str(clue.get("kind") or "").strip()
        if text and kind != "knowledge_boundary":
            values.append(text)
    return values


def _has_overconfident_cultural_claim(text: str, evidence: dict) -> bool:
    if not evidence:
        return False
    response_mode = str(evidence.get("response_mode") or "")
    has_boundary = any(
        isinstance(clue, dict) and str(clue.get("kind") or "") == "knowledge_boundary"
        for clue in evidence.get("user_clues", [])
        if isinstance(evidence.get("user_clues"), list)
    )
    if not has_boundary and response_mode != "no_knowledge_claim":
        return False
    if any(term in text for term in CULTURAL_UNCERTAINTY_TERMS):
        return False
    return any(term in text for term in CULTURAL_FABRICATION_TERMS)


def _missed_user_cultural_clue(text: str, evidence: dict) -> bool:
    clues = _evidence_user_clues(evidence)
    if not clues:
        return False
    return not any(clue in text for clue in clues)


def _shallow_anchor_echo(text: str, evidence: dict) -> bool:
    anchor_value = str(evidence.get("anchor_value") or "").strip()
    if not anchor_value or anchor_value not in text:
        return False
    clues = _evidence_user_clues(evidence)
    if not clues:
        return False
    return not any(clue in text for clue in clues)
```

Update `_has_fabricated_cultural_claim` to inspect `anchor_evidence`:

```python
    evidence = _anchor_evidence(policy)
    forbidden_claims = set(evidence.get("forbidden_claims") or []) if evidence else set()
    if forbidden_claims and any(term in text and term not in user_text for term in CULTURAL_FABRICATION_TERMS):
        return True
```

In `_conversation_experience_reasons`, after fabricated claim check:

```python
    evidence = _anchor_evidence(policy)
    if _has_overconfident_cultural_claim(text, evidence):
        reasons.append("overconfident_cultural_claim")
    if _missed_user_cultural_clue(text, evidence):
        reasons.append("missed_user_cultural_clue")
    if _shallow_anchor_echo(text, evidence):
        reasons.append("shallow_anchor_echo")
```

Add repair prompt hints in the helper that already maps labels into repair instructions:

```python
    if "overconfident_cultural_claim" in labels:
        lines.append("- overconfident_cultural_claim：用户没有给出的作品细节不要说成事实；只抓住用户给出的线索。")
    if "shallow_anchor_echo" in labels:
        lines.append("- shallow_anchor_echo：不要只复读锚点名，要回应用户给出的主题或画面。")
    if "missed_user_cultural_clue" in labels:
        lines.append("- missed_user_cultural_clue：回复里要出现用户给出的文化线索，而不只是作品名或人物名。")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversation_control_rag.py -q
```

Expected: all tests pass.

---

### Task 4: Conversation Quality Eval Fixtures

**Files:**
- Modify: `backend/tests/evals/fixtures_conversation_quality.json`
- Modify: `backend/tests/evals/test_conversation_quality.py`

- [ ] **Step 1: Add failing eval support tests**

In `test_conversation_quality.py`, extend `quality_report` to support new `must` flags after writing fixture cases:

- `no_overconfident_cultural_claim`
- `not_shallow_anchor_echo`
- `cultural_user_clue_used`

Before implementation, add fixture cases with `expected_negative_failures` containing the new labels. Running the eval should fail because the labels are not emitted.

Add cases:

```json
{
  "id": "cultural_anchor_uncertain_book_uses_user_clue",
  "category": "conversation_move_policy",
  "user_mode": "adult",
  "intent": "other",
  "user_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
  "recent_messages": [],
  "retrieved_memories": [],
  "retrieved_counseling_examples": [],
  "positive_response": "那我们先不假装已经知道很多，只抓住你给出的这条线索：《德米安》和“自我寻找”放在一起时，像是在问一个人怎么慢慢分辨什么是自己的声音。",
  "negative_response": "《德米安》的主角最后明白自我寻找就是摆脱所有关系，所以你现在也应该切断关系。",
  "must": ["topic_anchor_continued", "anchor_user_words", "no_fabricated_cultural_claim", "no_overconfident_cultural_claim", "cultural_user_clue_used"],
  "must_not": [],
  "anchors": ["德米安", "自我寻找"],
  "min_score": 0.85,
  "expected_negative_failures": ["fabricated_cultural_claim", "overconfident_cultural_claim"]
}
```

```json
{
  "id": "cultural_anchor_vague_quote_no_attribution_guess",
  "category": "conversation_move_policy",
  "user_mode": "adult",
  "intent": "other",
  "user_text": "我记不清原句了，大概是说人一直被什么东西推着走",
  "recent_messages": [],
  "retrieved_memories": [],
  "retrieved_counseling_examples": [],
  "positive_response": "那就先不追出处，也不硬猜原句。你给出的这个画面已经很清楚：人像一直被什么东西推着走，慢下来都不太被允许。",
  "negative_response": "这句应该是某位诗人写的原句，作者想表达现代人的命运，所以你现在也是这种命运。",
  "must": ["anchor_user_words", "no_fabricated_cultural_claim", "no_overconfident_cultural_claim", "cultural_user_clue_used"],
  "must_not": [],
  "anchors": ["推着走"],
  "min_score": 0.85,
  "expected_negative_failures": ["fabricated_cultural_claim", "overconfident_cultural_claim"]
}
```

```json
{
  "id": "cultural_anchor_shallow_echo_fails",
  "category": "conversation_move_policy",
  "user_mode": "adult",
  "intent": "other",
  "user_text": "我没读过《德米安》，只是听别人说它和自我寻找有关",
  "recent_messages": [],
  "retrieved_memories": [],
  "retrieved_counseling_examples": [],
  "positive_response": "《德米安》这个名字先放在“自我寻找”这条线上看，会更像是在问一个人怎么辨认自己的声音。",
  "negative_response": "《德米安》这个名字确实挺重的，也很值得聊。",
  "must": ["topic_anchor_continued", "anchor_user_words", "not_shallow_anchor_echo", "cultural_user_clue_used"],
  "must_not": [],
  "anchors": ["德米安", "自我寻找"],
  "min_score": 0.85,
  "expected_negative_failures": ["shallow_anchor_echo", "missed_user_cultural_clue"]
}
```

- [ ] **Step 2: Run eval test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evals\test_conversation_quality.py -q
```

Expected: new cases fail until scoring support is added.

- [ ] **Step 3: Implement eval scoring helpers**

In `test_conversation_quality.py`, add:

```python
def _has_overconfident_cultural_claim(case: dict[str, Any], text: str) -> bool:
    if has_any(text, CULTURAL_UNCERTAINTY_TERMS):
        return False
    user_text = str(case.get("user_text") or "")
    uncertain_user = has_any(user_text, ("没读过", "没看过", "只是听说", "听别人说", "不确定", "记不清", "不知道准不准"))
    return uncertain_user and any(term in text and term not in user_text for term in CULTURAL_FABRICATION_TERMS)


def _missed_cultural_user_clue(case: dict[str, Any], text: str) -> bool:
    clue_terms = [anchor for anchor in case.get("anchors", []) if str(anchor).strip()]
    if not clue_terms:
        return False
    return not any(term in text for term in clue_terms)


def _is_shallow_anchor_echo(case: dict[str, Any], text: str) -> bool:
    anchors = [anchor for anchor in case.get("anchors", []) if str(anchor).strip()]
    if len(anchors) < 2:
        return False
    primary, *clues = anchors
    return primary in text and not any(clue in text for clue in clues)
```

Then in `quality_report`:

```python
    if "no_overconfident_cultural_claim" in must and _has_overconfident_cultural_claim(case, text):
        soft_failures.append("overconfident_cultural_claim")
    if "cultural_user_clue_used" in must and _missed_cultural_user_clue(case, text):
        soft_failures.append("missed_user_cultural_clue")
    if "not_shallow_anchor_echo" in must and _is_shallow_anchor_echo(case, text):
        soft_failures.append("shallow_anchor_echo")
```

- [ ] **Step 4: Run eval and verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evals\test_conversation_quality.py -q
```

Expected: eval tests pass, including new positive and negative cultural cases.

---

### Task 5: Integration Verification

**Files:**
- No new production files.
- Verify modified files from Tasks 1-4.

- [ ] **Step 1: Run targeted cultural and prompt tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_conversation_move_policy.py tests\test_dialogue_prompt_builder.py tests\test_conversation_control_rag.py tests\evals\test_conversation_quality.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run broader related regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/evals/test_conversation_quality.py tests/evals/test_memory_use_quality.py tests/test_conversation_quality.py tests/test_dialogue_prompt_builder.py tests/test_conversation_control_rag.py tests/test_conversation_move_policy.py tests/test_risk_policy.py tests/test_graph_runtime_streaming.py tests/test_chat_idempotency.py tests/test_safety_evaluation.py -q
```

Expected: all selected tests pass or preserve existing unrelated skips.

- [ ] **Step 3: Run syntax and whitespace checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app\services\conversation_move_policy.py app\services\dialogue_prompt_builder.py app\graphs\nodes\validator_nodes.py
git diff --check
```

Expected: `py_compile` exits 0; `git diff --check` has no errors other than known CRLF warnings if present.

- [ ] **Step 4: Review final diff**

Run:

```powershell
git diff --stat
git status --short
```

Expected: only intended files are modified or added. Do not stage unrelated untracked files under `.playwright-mcp`, `backend/data`, or existing unrelated plan files.
