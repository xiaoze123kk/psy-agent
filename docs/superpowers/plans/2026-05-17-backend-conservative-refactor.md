# Backend Conservative Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor backend large files into smaller internal helper modules while preserving all API behavior, public import paths, monkeypatch points, and tests.

**Architecture:** Keep current facade modules (`memory_service.py`, `chat_service.py`, `conversation_move_policy.py`, `validator_nodes.py`) as stable public entry points. Extract pure helpers and local orchestration into adjacent private modules, then import them back under the original private names where tests or existing code depend on those names.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, LangGraph node modules, pytest.

---

## Scope And File Map

**Create:**
- `backend/tests/test_backend_refactor_contract.py`: characterization tests for stable import paths and monkeypatch compatibility.
- `backend/app/services/memory_scoring.py`: pure memory text cleanup, tokenization, and similarity helpers.
- `backend/app/services/chat_turn_lifecycle.py`: chat turn idempotency, replay, completion, failure, and trace-safe payload helpers.
- `backend/app/services/chat_streaming.py`: stream chunk, graph update, and heartbeat event helpers.
- `backend/app/services/conversation_policy_anchors.py`: cultural/person anchor extraction and anchor evidence helpers.
- `backend/app/services/conversation_policy_adaptation.py`: recent feedback and short-term adaptation state helpers.
- `backend/app/services/conversation_policy_structure.py`: reply structure detection and structure style helpers.
- `backend/app/graphs/nodes/validator_experience.py`: response experience validator rules and severity helpers.

**Modify:**
- `backend/app/services/memory_service.py`: import extracted scoring helpers; keep `_content_similarity` patchable from this module.
- `backend/app/services/chat_service.py`: import lifecycle and streaming helpers; keep `graph_runtime` and `settings` patchable from this module.
- `backend/app/services/conversation_move_policy.py`: import anchor, adaptation, and structure helpers; keep `build_conversation_move_policy` and `default_actions_for_conversation_move_policy`.
- `backend/app/graphs/nodes/validator_nodes.py`: import extracted experience validator helpers; keep `deepseek_client` in this module for existing patches.

**Do not modify:**
- `backend/app/db/models.py`
- `backend/app/api/v1/endpoints/*`
- `database/migrations/*`
- `frontend/*`
- `backend/data/*`
- `.playwright-mcp/*`
- log files, caches, screenshots, generated artifacts

## Task 1: Add Refactor Contract Tests

**Files:**
- Create: `backend/tests/test_backend_refactor_contract.py`

- [ ] **Step 1: Write failing characterization tests**

Create `backend/tests/test_backend_refactor_contract.py` with this exact content:

```python
from __future__ import annotations

from unittest.mock import patch


def test_refactor_helper_modules_are_importable() -> None:
    from app.graphs.nodes import validator_experience
    from app.services import (
        chat_streaming,
        chat_turn_lifecycle,
        conversation_policy_adaptation,
        conversation_policy_anchors,
        conversation_policy_structure,
        memory_scoring,
    )

    assert callable(memory_scoring.content_similarity)
    assert callable(chat_turn_lifecycle.request_hash)
    assert callable(chat_streaming.iter_stream_chunks)
    assert callable(conversation_policy_anchors.anchor_evidence)
    assert callable(conversation_policy_adaptation.adaptation_state_from_recent)
    assert callable(conversation_policy_structure.reply_structure_signature)
    assert callable(validator_experience.experience_validator_reasons)


def test_existing_memory_similarity_patch_path_remains_stable() -> None:
    from app.services import memory_service

    calls: list[tuple[str, str]] = []

    def counted_similarity(left: str, right: str) -> float:
        calls.append((left, right))
        return 0.42

    with patch("app.services.memory_service._content_similarity", side_effect=counted_similarity):
        assert memory_service._content_similarity("left", "right") == 0.42

    assert calls == [("left", "right")]


def test_existing_chat_service_patch_points_remain_stable() -> None:
    from app.services import chat_service

    original_graph_runtime = chat_service.graph_runtime
    original_settings = chat_service.settings

    class FakeRuntime:
        pass

    try:
        fake_runtime = FakeRuntime()
        chat_service.graph_runtime = fake_runtime
        chat_service.settings = original_settings
        assert chat_service.graph_runtime is fake_runtime
        assert chat_service.settings is original_settings
    finally:
        chat_service.graph_runtime = original_graph_runtime
        chat_service.settings = original_settings


def test_existing_validator_private_severity_helper_remains_stable() -> None:
    from app.graphs.nodes import validator_nodes

    reasons = ["failed_short_term_adaptation", "too_many_questions"]

    assert validator_nodes._blocking_experience_reasons(reasons) == ["failed_short_term_adaptation"]
```

- [ ] **Step 2: Run the new tests to verify they fail for the missing helper modules**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py -q
```

Expected: FAIL at `test_refactor_helper_modules_are_importable` with an import error for one of the new helper modules.

- [ ] **Step 3: Commit the contract tests**

```powershell
git add backend/tests/test_backend_refactor_contract.py
git commit -m "test: 固定后端重构兼容入口"
```

## Task 2: Extract Memory Scoring Helpers

**Files:**
- Create: `backend/app/services/memory_scoring.py`
- Modify: `backend/app/services/memory_service.py`
- Test: `backend/tests/test_backend_refactor_contract.py`
- Test: `backend/tests/test_memory_service.py`

- [ ] **Step 1: Create `memory_scoring.py`**

Create `backend/app/services/memory_scoring.py` with this exact content:

```python
from __future__ import annotations

import re
from difflib import SequenceMatcher


def clean_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    if limit is not None and len(text) > limit:
        return text[: max(limit - 1, 0)] + "…"
    return text


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    cjk_chars = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return ascii_words | cjk_chars


def term_similarity(query: str, document: str) -> float:
    query_terms = tokenize(query)
    if not query_terms:
        return 0.0
    doc_terms = tokenize(document)
    if not doc_terms:
        return 0.0
    return len(query_terms & doc_terms) / max(len(query_terms), 1)


def content_similarity(left: str, right: str) -> float:
    left_text = clean_text(left).lower()
    right_text = clean_text(right).lower()
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def should_compare_memory_content(existing_content: object, candidate_content: object) -> bool:
    left = clean_text(existing_content)
    right = clean_text(candidate_content)
    if not left or not right:
        return False
    if left == right:
        return True

    shorter_length = min(len(left), len(right))
    longer_length = max(len(left), len(right))
    if shorter_length / longer_length < 0.45:
        return False
    if shorter_length < 12:
        return True
    return bool(tokenize(left) & tokenize(right))
```

- [ ] **Step 2: Update `memory_service.py` imports**

In `backend/app/services/memory_service.py`, remove these imports because the new helper module owns them:

```python
import re
from difflib import SequenceMatcher
```

Add this import block after the existing `milvus_store` import:

```python
from app.services.memory_scoring import (
    clean_text as _clean_text,
    content_similarity as _content_similarity,
    should_compare_memory_content as _should_compare_memory_content,
    term_similarity as _term_similarity,
    tokenize as _tokenize,
)
```

- [ ] **Step 3: Remove moved function bodies from `memory_service.py`**

Delete these exact top-level definitions from `backend/app/services/memory_service.py` after the import aliases are in place:

- `_clean_text`
- `_tokenize`
- `_term_similarity`
- `_content_similarity`
- `_should_compare_memory_content`

Do not delete `_derive_title`, `_derive_tags`, `_freshness_warning`, `_memory_document`, `_score_memory`, or `_vector_score_memory`. They should keep using the imported private aliases.

- [ ] **Step 4: Verify memory compatibility**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_memory_service.py -q
```

Expected: PASS. The contract test must prove `app.services.memory_service._content_similarity` is still patchable.

- [ ] **Step 5: Commit memory extraction**

```powershell
git add backend/app/services/memory_scoring.py backend/app/services/memory_service.py backend/tests/test_backend_refactor_contract.py
git commit -m "refactor: 拆分记忆评分辅助函数"
```

## Task 3: Extract Chat Turn Lifecycle And Streaming Helpers

**Files:**
- Create: `backend/app/services/chat_turn_lifecycle.py`
- Create: `backend/app/services/chat_streaming.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_idempotency.py`
- Test: `backend/tests/test_memory.py`
- Test: `backend/tests/test_backend_refactor_contract.py`

- [ ] **Step 1: Create `chat_streaming.py`**

Create `backend/app/services/chat_streaming.py` with this exact content:

```python
from __future__ import annotations

from time import monotonic


ChatStreamEvent = tuple[str, dict[str, object]]


def iter_stream_chunks(text: str, *, chunk_size: int = 6):
    buffer = ""
    stop_chars = set("。！？?!\n")
    for char in text:
        buffer += char
        if len(buffer) >= chunk_size or char in stop_chars:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer


def graph_update_event(node: str, **data: object) -> ChatStreamEvent:
    return "graph_update", {"node": node, "status": "completed", **data}


def heartbeat_event(started_at: float) -> ChatStreamEvent:
    return "heartbeat", {"status": "running", "elapsed_ms": int((monotonic() - started_at) * 1000)}
```

- [ ] **Step 2: Create `chat_turn_lifecycle.py` by moving exact lifecycle code**

Create `backend/app/services/chat_turn_lifecycle.py` and move these exact definitions from `chat_service.py` into it without changing their bodies except for dropping leading underscores from exported helper names:

- `TurnClaim`
- `_request_hash` renamed to `request_hash`
- `_json_safe` renamed to `json_safe`
- `_dict_copy` renamed to `dict_copy`
- `_set_quality_next_turn_signal` renamed to `set_quality_next_turn_signal`
- `_backfill_previous_turn_next_signal` renamed to `backfill_previous_turn_next_signal`
- `_turn_metadata` renamed to `turn_metadata`
- `_turn_response_fields` renamed to `turn_response_fields`
- `_turn_conflict` renamed to `turn_conflict`
- `_wait_for_running_turn` renamed to `wait_for_running_turn`
- `_claim_turn` renamed to `claim_turn`
- `_complete_turn` renamed to `complete_turn`
- `_mark_turn_failed` renamed to `mark_turn_failed`
- `_replay_turn_result` renamed to `replay_turn_result`

Use this import and constant header in the new module:

```python
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ConversationThread, ConversationTurn, Message, User, generate_uuid, utcnow
from app.schemas.chat import SendMessageRequest
from app.services.conversation_quality_service import infer_next_turn_signal


logger = logging.getLogger("app.services.chat_service")
TURN_RUNNING_WAIT_SECONDS = 1.0
TURN_RUNNING_POLL_INTERVAL_SECONDS = 0.1
```

When moving function bodies, update internal calls inside `chat_turn_lifecycle.py` from old private names to new public local names:

- `_request_hash` calls become `request_hash` calls.
- `_turn_conflict` calls become `turn_conflict` calls.
- `_wait_for_running_turn` calls become `wait_for_running_turn` calls.
- `_turn_response_fields` calls become `turn_response_fields` calls.
- `_json_safe` calls become `json_safe` calls.
- `_set_quality_next_turn_signal` calls become `set_quality_next_turn_signal` calls.

- [ ] **Step 3: Import lifecycle and streaming helpers back into `chat_service.py`**

In `backend/app/services/chat_service.py`, remove imports that are no longer used after the move:

```python
import hashlib
from sqlalchemy.exc import IntegrityError
```

Keep these imports in `chat_service.py` because the facade still owns graph orchestration and patches:

```python
import asyncio
import json
import logging
from contextlib import suppress
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.graph_runtime import GraphRuntime
```

Add these import blocks:

```python
from app.services.chat_streaming import (
    ChatStreamEvent,
    graph_update_event as _graph_update_event,
    heartbeat_event as _heartbeat_event,
    iter_stream_chunks as _iter_stream_chunks,
)
from app.services.chat_turn_lifecycle import (
    TurnClaim,
    backfill_previous_turn_next_signal as _backfill_previous_turn_next_signal,
    claim_turn as _claim_turn,
    complete_turn as _complete_turn,
    mark_turn_failed as _mark_turn_failed,
    replay_turn_result as _replay_turn_result,
    turn_metadata as _turn_metadata,
)
```

Delete the moved definitions from `chat_service.py`:

- `TurnClaim`
- `_request_hash`
- `_json_safe`
- `_dict_copy`
- `_set_quality_next_turn_signal`
- `_backfill_previous_turn_next_signal`
- `_turn_metadata`
- `_turn_response_fields`
- `_turn_conflict`
- `_wait_for_running_turn`
- `_claim_turn`
- `_complete_turn`
- `_mark_turn_failed`
- `_replay_turn_result`
- `_iter_stream_chunks`
- `_graph_update_event`
- `_heartbeat_event`

Do not move `graph_runtime = GraphRuntime()` or `settings`. Existing tests patch those names on `app.services.chat_service`.

- [ ] **Step 4: Verify chat behavior**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_chat_idempotency.py tests/test_memory.py -q
```

Expected: PASS. The contract test must prove `chat_service.graph_runtime` and `chat_service.settings` are still patchable.

- [ ] **Step 5: Commit chat extraction**

```powershell
git add backend/app/services/chat_service.py backend/app/services/chat_streaming.py backend/app/services/chat_turn_lifecycle.py backend/tests/test_backend_refactor_contract.py
git commit -m "refactor: 拆分聊天轮次生命周期"
```

## Task 4: Extract Conversation Move Policy Helpers

**Files:**
- Create: `backend/app/services/conversation_policy_anchors.py`
- Create: `backend/app/services/conversation_policy_adaptation.py`
- Create: `backend/app/services/conversation_policy_structure.py`
- Modify: `backend/app/services/conversation_move_policy.py`
- Test: `backend/tests/test_conversation_move_policy.py`
- Test: `backend/tests/test_dialogue_prompt_builder.py`
- Test: `backend/tests/test_backend_refactor_contract.py`

- [ ] **Step 1: Create `conversation_policy_anchors.py` by moving anchor code**

Move these constants and helper definitions from `conversation_move_policy.py` into `backend/app/services/conversation_policy_anchors.py` without changing literal text:

- `HIGH_RISK_LEVELS`
- `LITERARY_CONTEXT_TERMS`
- `PHILOSOPHICAL_CONTEXT_TERMS`
- `MEDIA_TERMS`
- `DAILY_DETAIL_TERMS`
- `METAPHOR_TERMS`
- `LIGHT_CHAT_TERMS`
- `DISTRESS_TERMS`
- `SHORT_FOLLOWUP_TERMS`
- `GENERIC_PERSON_ANCHORS`
- `CULTURAL_ANCHOR_TYPES`
- `KNOWLEDGE_BOUNDARY_TERMS`
- `THEME_CLUE_TERMS`
- `COMMON_CULTURAL_ANCHORS`
- `SELF_REFERENCE_TERMS`
- `_text` renamed to `text_from_state`
- `_has_any` renamed to `has_any`
- `_recent_messages` renamed to `recent_messages`
- `_recent_high_risk_seen` renamed to `recent_high_risk_seen`
- `_extract_book_title` renamed to `extract_book_title`
- `_recent_quoted_titles` renamed to `recent_quoted_titles`
- `_recent_title_mentioned` renamed to `recent_title_mentioned`
- `_suppressed_recent_anchors` renamed to `suppressed_recent_anchors`
- `_common_cultural_anchor` renamed to `common_cultural_anchor`
- `_anchor_clue` renamed to `anchor_clue`
- `_dedupe_clues` renamed to `dedupe_clues`
- `_user_clues_for_anchor` renamed to `user_clues_for_anchor`
- `_clean_person_candidate` renamed to `clean_person_candidate`
- `_person_anchor_value` renamed to `person_anchor_value`
- `_anchor_value` renamed to `anchor_value`
- `_topic_anchor_type` renamed to `topic_anchor_type`
- `_cultural_response_mode` renamed to `cultural_response_mode`
- `_anchor_evidence` renamed to `anchor_evidence`
- `_is_cultural_lane_anchor` renamed to `is_cultural_lane_anchor`
- `_is_short_followup` renamed to `is_short_followup`

Use this module header:

```python
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
```

Rename the moved functions by dropping their leading underscores. Update local calls inside the new module to use the new non-underscore names.

- [ ] **Step 2: Create `conversation_policy_adaptation.py` by moving recent feedback code**

Move these constants and helper definitions from `conversation_move_policy.py` into `backend/app/services/conversation_policy_adaptation.py` without changing literal text:

- `ANALYSIS_BOUNDARY_TERMS`
- `QUESTION_BOUNDARY_TERMS`
- `SAFETY_BOUNDARY_TERMS`
- `PAUSE_REQUEST_TERMS`
- `ADAPTATION_COUNT_KEYS`
- `NEGATIVE_EXPLICIT_FEEDBACK`
- `_correction_type` renamed to `correction_type`
- `_matched_terms` renamed to `matched_terms`
- `_is_pause_request` renamed to `is_pause_request`
- `_wants_to_keep_anchor_light` renamed to `wants_to_keep_anchor_light`
- `_latest_assistant_policy` renamed to `latest_assistant_policy`
- `_quality_user_signal` renamed to `quality_user_signal`
- `_latest_assistant_explicit_feedback` renamed to `latest_assistant_explicit_feedback`
- `_nonnegative_int` renamed to `nonnegative_int`
- `_adaptation_state_from_recent` renamed to `adaptation_state_from_recent`

Use this module header:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.conversation_policy_anchors import has_any
```

Rename the moved functions by dropping their leading underscores. Update local calls inside the new module to use the new non-underscore names.

- [ ] **Step 3: Create `conversation_policy_structure.py` by moving structure code**

Move these helper definitions from `conversation_move_policy.py` into `backend/app/services/conversation_policy_structure.py` without changing literal text:

- `_recent_assistant_opening_mode` renamed to `recent_assistant_opening_mode`
- `_recent_assistant_contents` renamed to `recent_assistant_contents`
- `_reply_structure_signature` renamed to `reply_structure_signature`
- `_recent_reused_structure` renamed to `recent_reused_structure`
- `_base_structure_mode` renamed to `base_structure_mode`
- `_structure_mode_for` renamed to `structure_mode_for`
- `_structure_style` renamed to `structure_style`

Use this module header:

```python
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
```

Rename the moved functions by dropping their leading underscores. Update local calls inside the new module to use the new non-underscore names.

- [ ] **Step 4: Import helper aliases back into `conversation_move_policy.py`**

In `backend/app/services/conversation_move_policy.py`, add imports that preserve the original private names used by the remaining orchestration code:

```python
from app.services.conversation_policy_adaptation import (
    adaptation_state_from_recent as _adaptation_state_from_recent,
    correction_type as _correction_type,
    is_pause_request as _is_pause_request,
    latest_assistant_explicit_feedback as _latest_assistant_explicit_feedback,
    matched_terms as _matched_terms,
    wants_to_keep_anchor_light as _wants_to_keep_anchor_light,
)
from app.services.conversation_policy_anchors import (
    CULTURAL_ANCHOR_TYPES,
    DAILY_DETAIL_TERMS,
    DISTRESS_TERMS,
    HIGH_RISK_LEVELS,
    LIGHT_CHAT_TERMS,
    METAPHOR_TERMS,
    SELF_REFERENCE_TERMS,
    anchor_evidence as _anchor_evidence,
    anchor_value as _anchor_value,
    has_any as _has_any,
    is_cultural_lane_anchor as _is_cultural_lane_anchor,
    is_short_followup as _is_short_followup,
    recent_high_risk_seen as _recent_high_risk_seen,
    recent_messages as _recent_messages,
    suppressed_recent_anchors as _suppressed_recent_anchors,
    text_from_state as _text,
    topic_anchor_type as _topic_anchor_type,
)
from app.services.conversation_policy_structure import (
    recent_reused_structure as _recent_reused_structure,
    structure_mode_for as _structure_mode_for,
    structure_style as _structure_style,
)
```

Delete the moved constants and definitions from `conversation_move_policy.py` after adding these imports. Keep `build_conversation_move_policy`, `default_actions_for_conversation_move_policy`, `_intent_lanes_for`, `_voice_contract_for`, and the remaining top-level orchestration helpers in `conversation_move_policy.py`.

- [ ] **Step 5: Verify conversation move policy behavior**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_conversation_move_policy.py tests/test_dialogue_prompt_builder.py -q
```

Expected: PASS. `build_conversation_move_policy` and `default_actions_for_conversation_move_policy` must keep returning the same policy fields and actions as before.

- [ ] **Step 6: Commit conversation policy extraction**

```powershell
git add backend/app/services/conversation_move_policy.py backend/app/services/conversation_policy_anchors.py backend/app/services/conversation_policy_adaptation.py backend/app/services/conversation_policy_structure.py backend/tests/test_backend_refactor_contract.py
git commit -m "refactor: 拆分对话走向策略辅助逻辑"
```

## Task 5: Extract Validator Experience Rules

**Files:**
- Create: `backend/app/graphs/nodes/validator_experience.py`
- Modify: `backend/app/graphs/nodes/validator_nodes.py`
- Test: `backend/tests/test_conversation_control_rag.py`
- Test: `backend/tests/evals/test_conversation_quality.py`
- Test: `backend/tests/test_backend_refactor_contract.py`

- [ ] **Step 1: Create `validator_experience.py` by moving experience validator code**

Move these constants and helper definitions from `validator_nodes.py` into `backend/app/graphs/nodes/validator_experience.py` without changing literal text:

- `EXPERIENCE_BANNED_TERMS`
- `MORALIZING_TERMS`
- `FIRST_TURN_REFERRAL_TERMS`
- `QUESTION_MARKS`
- `SAFETY_QUESTION_PHRASES`
- `EXPERIENCE_REASON_SEVERITY`
- `PSYCHOLOGIZING_TERMS`
- `GENERIC_BUTTON_TERMS`
- `FORMULAIC_OPENINGS`
- `COUNSELING_RESTART_TERMS`
- `OLD_CORRECTION_MODE_TERMS`
- `DAILY_OR_METAPHOR_ANCHOR_HINT_TERMS`
- `CULTURAL_ANCHOR_TYPES`
- `CULTURAL_FABRICATION_TERMS`
- `CULTURAL_UNCERTAINTY_TERMS`
- `CULTURAL_FORBIDDEN_CLAIM_TERMS`
- `CULTURAL_CLUE_ALIASES`
- `_question_count` renamed to `question_count`
- `_ends_with_question` renamed to `ends_with_question`
- `_int_or_default` renamed to `int_or_default`
- `_question_limit` renamed to `question_limit`
- `_contains_safety_question` renamed to `contains_safety_question`
- `_conversation_policy` renamed to `conversation_policy`
- `_policy_voice_contract` renamed to `policy_voice_contract`
- `_policy_adaptation_state` renamed to `policy_adaptation_state`
- `_policy_topic_anchor` renamed to `policy_topic_anchor`
- `_policy_anchor_terms` renamed to `policy_anchor_terms`
- `_recent_formulaic_opening_reused` renamed to `recent_formulaic_opening_reused`
- `_reply_structure_signature` renamed to `reply_structure_signature`
- `_recent_reply_structure_signatures` renamed to `recent_reply_structure_signatures`
- `_reused_reply_structure` renamed to `reused_reply_structure`
- `_anchor_evidence` renamed to `anchor_evidence`
- `_evidence_user_clues` renamed to `evidence_user_clues`
- `_evidence_has_knowledge_boundary` renamed to `evidence_has_knowledge_boundary`
- `_forbidden_claim_terms` renamed to `forbidden_claim_terms`
- `_has_forbidden_cultural_claim` renamed to `has_forbidden_cultural_claim`
- `_has_fabricated_cultural_claim` renamed to `has_fabricated_cultural_claim`
- `_has_overconfident_cultural_claim` renamed to `has_overconfident_cultural_claim`
- `_cultural_clue_in_text` renamed to `cultural_clue_in_text`
- `_lane_user_clues` renamed to `lane_user_clues`
- `_lane_anchor_terms` renamed to `lane_anchor_terms`
- `_primary_lane_missed` renamed to `primary_lane_missed`
- `_expanded_forbidden_lane` renamed to `expanded_forbidden_lane`
- `_sentence_count` renamed to `sentence_count`
- `_sentence_budget_max` renamed to `sentence_budget_max`
- `_violated_voice_contract` renamed to `violated_voice_contract`
- `_failed_short_term_adaptation` renamed to `failed_short_term_adaptation`
- `_missed_user_cultural_clue` renamed to `missed_user_cultural_clue`
- `_shallow_anchor_echo` renamed to `shallow_anchor_echo`
- `_conversation_experience_reasons` renamed to `conversation_experience_reasons`
- `experience_validator_reasons`
- `_experience_reason_severity` renamed to `experience_reason_severity`
- `_experience_warning_reasons` renamed to `experience_warning_reasons`
- `_blocking_experience_reasons` renamed to `blocking_experience_reasons`
- `_combined_experience_reasons` renamed to `combined_experience_reasons`
- `_experience_metadata` renamed to `experience_metadata`
- `_validator_severity` renamed to `validator_severity`

Use this module header:

```python
from __future__ import annotations

import re

from app.graphs.nodes.common import AgentState
```

Rename moved helper functions by dropping their leading underscores. Update local calls inside the new module to use the new non-underscore names.

- [ ] **Step 2: Import validator helper aliases back into `validator_nodes.py`**

In `backend/app/graphs/nodes/validator_nodes.py`, keep these imports and globals in place:

```python
import logging
import re

from app.graphs.nodes.common import AgentState, memory_context, parse_actions_reply
from app.services.conversation_quality_service import build_conversation_quality_trace
from app.services.deepseek_client import deepseek_client
from app.services.dialogue_prompt_builder import build_dialogue_prompt_parts
```

Add this import block:

```python
from app.graphs.nodes.validator_experience import (
    blocking_experience_reasons as _blocking_experience_reasons,
    combined_experience_reasons as _combined_experience_reasons,
    conversation_policy as _conversation_policy,
    experience_metadata as _experience_metadata,
    experience_validator_reasons,
    experience_warning_reasons as _experience_warning_reasons,
    validator_severity as _validator_severity,
)
```

Delete the moved constants and definitions from `validator_nodes.py`. Keep `validator_reasons`, `_quality_trace_for_result`, `_with_quality_trace`, `_repair_focus_block`, `_repair_mode_for_state`, `_regenerate_reply_with_model`, `is_safety_delivery_path`, `failed_no_reply_validation_result`, and `response_validator` in `validator_nodes.py`.

- [ ] **Step 3: Verify validator behavior and patch compatibility**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_conversation_control_rag.py tests/evals/test_conversation_quality.py -q
```

Expected: PASS. Existing patches targeting `app.graphs.nodes.validator_nodes.deepseek_client.chat` must still work because `deepseek_client` remains in `validator_nodes.py`.

- [ ] **Step 4: Commit validator extraction**

```powershell
git add backend/app/graphs/nodes/validator_nodes.py backend/app/graphs/nodes/validator_experience.py backend/tests/test_backend_refactor_contract.py
git commit -m "refactor: 拆分响应体验校验规则"
```

## Task 6: Final Backend Verification

**Files:**
- Modify only if a previous task left import or formatting issues in touched backend files.
- Test: targeted backend test suite.

- [ ] **Step 1: Run compile smoke**

Run from `backend/`:

```powershell
python -m compileall app
```

Expected: exits with code 0.

- [ ] **Step 2: Run targeted regression tests**

Run from `backend/`:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_memory_service.py tests/test_memory.py tests/test_chat_idempotency.py tests/test_conversation_move_policy.py tests/test_conversation_control_rag.py tests/test_dialogue_prompt_builder.py tests/test_graph_runtime_streaming.py tests/test_response_memory_continuity.py -q
```

Expected: PASS. If tests requiring local database or external services fail, record the exact failing test names and error messages, then run the pure unit subset:

```powershell
python -m pytest tests/test_backend_refactor_contract.py tests/test_memory_service.py tests/test_conversation_move_policy.py tests/test_conversation_control_rag.py tests/test_dialogue_prompt_builder.py -q
```

Expected: PASS.

- [ ] **Step 3: Check changed files are in scope**

Run from repository root:

```powershell
git diff --name-status
```

Expected changed paths are limited to:

```text
backend/app/services/memory_service.py
backend/app/services/memory_scoring.py
backend/app/services/chat_service.py
backend/app/services/chat_streaming.py
backend/app/services/chat_turn_lifecycle.py
backend/app/services/conversation_move_policy.py
backend/app/services/conversation_policy_anchors.py
backend/app/services/conversation_policy_adaptation.py
backend/app/services/conversation_policy_structure.py
backend/app/graphs/nodes/validator_nodes.py
backend/app/graphs/nodes/validator_experience.py
backend/tests/test_backend_refactor_contract.py
```

No frontend, database migration, data, cache, log, screenshot, or `.playwright-mcp` files should be staged.

- [ ] **Step 4: Commit final verification fixes when Step 1 or Step 2 changed files**

If Step 1 or Step 2 required a small import/format fix, commit it:

```powershell
git add backend/app/services backend/app/graphs/nodes backend/tests/test_backend_refactor_contract.py
git commit -m "refactor: 完成后端保守重构验证"
```

When Step 1 and Step 2 required no file edits after Task 5, skip this step and leave the history at the Task 5 commit.

## Self-Review Notes

- Spec coverage: The plan preserves public module paths, keeps monkeypatch points stable, avoids database/frontend/data files, and verifies with the tests named in the design.
- Placeholder scan: No task relies on unspecified future behavior; each extraction names exact files, symbols, commands, and expected outcomes.
- Type consistency: `ChatStreamEvent`, `TurnClaim`, `SendMessageRequest`, `ConversationTurn`, `Message`, `Session`, and `AgentState` are imported in the modules that use them.
