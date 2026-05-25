# Backend Risk Control Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace rigid visible safety replies with a backend risk policy system that keeps safety controls strict while making high-risk conversations feel continuous, low-pressure, and context-aware.

**Architecture:** Add a small `risk_policy` service that derives domain, immediacy, phase, length profile, allowed moves, and safe actions from `AgentState`. Feed that policy through `control_plane`, response nodes, tool gating, safe memory context, validators, graph runtime mapping, and chat persistence. Keep knowledge-base work out of scope because knowledge is currently disabled.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, SQLAlchemy, unittest/pytest, existing backend services under `backend/app`.

---

## File Structure

- Create `backend/app/services/risk_policy.py`: pure policy helpers for risk domain, immediacy, phase, response policy, length budgets, tool gate mode, and suggested actions.
- Create `backend/app/services/safety_context_service.py`: sanitize high-risk memory/context snippets into `safety_context_pack`.
- Create `backend/tests/test_risk_policy.py`: unit tests for policy derivation and length profiles.
- Create `backend/tests/test_safety_context_service.py`: unit tests for high-risk context filtering.
- Modify `backend/app/graphs/state.py`: add strategy fields to `AgentState`.
- Modify `backend/app/graphs/nodes/control_nodes.py`: call `risk_policy` and expose strategy fields.
- Modify `backend/app/graphs/nodes/response_nodes.py`: generate crisis/boundary/red-flag replies from policy, not static crisis templates.
- Modify `backend/app/graphs/nodes/validator_nodes.py`: add experience validator and policy-aware length checks.
- Modify `backend/app/services/memory_service.py`: allow high-risk safety memory types and sanitize returned visible fields.
- Modify `backend/app/services/tooling.py`: add safety tool gate mode and safe web search behavior.
- Modify `backend/app/services/chat_service.py`: build `safety_context_pack`, pass it to runtime, and persist policy metadata.
- Modify `backend/app/services/graph_runtime.py`: carry new fields through state, trace events, and result mapping.
- Modify tests:
  - `backend/tests/test_conversation_control_rag.py`
  - `backend/tests/test_tooling.py`
  - `backend/tests/test_graph_runtime_streaming.py`
  - `backend/tests/test_chat_idempotency.py` if metadata expectations need updating.

---

### Task 1: Add Risk Policy Service

**Files:**
- Create: `backend/app/services/risk_policy.py`
- Create: `backend/tests/test_risk_policy.py`

- [ ] **Step 1: Write failing tests for policy derivation**

Create `backend/tests/test_risk_policy.py`:

```python
from __future__ import annotations

import unittest

from app.services.risk_policy import (
    build_risk_response_policy,
    default_actions_for_policy,
    derive_immediacy,
    derive_risk_domain,
    derive_risk_phase,
    tool_gate_mode_for_state,
)


class RiskPolicyTests(unittest.TestCase):
    def test_self_harm_near_term_policy_uses_brief_first_contact(self) -> None:
        state = {
            "risk_level": "L3",
            "control_category": "self_harm_risk",
            "semantic_risk": {"means": True, "timeframe": "near_term"},
            "normalized_text": "我现在不想活了，那个东西就在手边",
            "recent_messages": [],
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_domain"], "self_harm")
        self.assertEqual(policy["immediacy"], "near_term")
        self.assertEqual(policy["risk_phase"], "first_contact")
        self.assertEqual(policy["length_profile"], "brief_first_contact")
        self.assertEqual(policy["char_budget"]["target"], 220)
        self.assertIn("micro_safety_step", policy["allowed_moves"])
        self.assertIn("professional_referral_first_turn", policy["forbidden_moves"])

    def test_deescalating_policy_allows_warm_medium_length(self) -> None:
        state = {
            "risk_level": "L2",
            "control_category": "self_harm_risk",
            "semantic_risk": {"protective_factor": True},
            "normalized_text": "我还在，暂时不会动",
            "recent_messages": [
                {"role": "user", "content": "我刚才真的很想伤害自己"},
                {"role": "assistant", "content": "我们先只过这一分钟。"},
            ],
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_phase"], "deescalating")
        self.assertEqual(policy["length_profile"], "warm_medium")
        self.assertGreater(policy["char_budget"]["target"], 300)

    def test_medical_request_maps_to_firm_brief(self) -> None:
        state = {
            "risk_level": "L0",
            "control_category": "diagnosis_or_medical_request",
            "normalized_text": "我能不能停药，剂量怎么调",
        }

        policy = build_risk_response_policy(state)

        self.assertEqual(policy["risk_domain"], "medical_request")
        self.assertEqual(policy["length_profile"], "firm_brief")
        self.assertIn("medication_or_dosage_advice", policy["forbidden_moves"])

    def test_tool_gate_mode_uses_safety_context_for_l2_l3(self) -> None:
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L2"}), "safety_context")
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L3"}), "safety_context")
        self.assertEqual(tool_gate_mode_for_state({"risk_level": "L1"}), "normal_context")
        self.assertEqual(
            tool_gate_mode_for_state({"risk_level": "L1", "control_category": "prompt_attack"}),
            "blocked_context",
        )

    def test_actions_follow_policy_without_professional_referral_first_turn(self) -> None:
        policy = {
            "risk_domain": "self_harm",
            "immediacy": "near_term",
            "risk_phase": "first_contact",
            "length_profile": "brief_first_contact",
        }

        actions = default_actions_for_policy(policy)

        self.assertEqual(actions, ["我还在", "我退开一点了", "我身边有人", "请继续跟我说"])
        self.assertFalse(any("咨询" in action or "医院" in action for action in actions))

    def test_direct_helpers_are_stable(self) -> None:
        self.assertEqual(derive_risk_domain({"control_category": "harm_to_other_risk"}), "harm_other")
        self.assertEqual(derive_immediacy({"semantic_risk": {"means": True}}), "near_term")
        self.assertEqual(derive_risk_phase({"risk_level": "L0", "recent_messages": []}), "first_contact")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_risk_policy.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.risk_policy'`.

- [ ] **Step 3: Implement `risk_policy.py`**

Create `backend/app/services/risk_policy.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}
BLOCKED_CONTEXT_CATEGORIES = {
    "prompt_attack",
    "diagnosis_or_medical_request",
    "dangerous_request",
}

DOMAIN_BY_CATEGORY = {
    "self_harm_risk": "self_harm",
    "harm_to_other_risk": "harm_other",
    "anger_toward_other": "harm_other",
    "victimization_risk": "victimization",
    "clinical_red_flag": "clinical_red_flag",
    "diagnosis_or_medical_request": "medical_request",
    "dependency_risk": "dependency",
    "sexual_boundary": "sexual_boundary",
    "prompt_attack": "prompt_attack",
}

LENGTH_BUDGETS = {
    "brief_first_contact": {"target": 220, "max": 360},
    "steady_short": {"target": 300, "max": 460},
    "warm_medium": {"target": 420, "max": 640},
    "supportive_medium": {"target": 520, "max": 820},
    "holding_longer": {"target": 700, "max": 980},
    "firm_brief": {"target": 220, "max": 360},
}

BASE_FORBIDDEN_MOVES = [
    "diagnosis",
    "medication_or_dosage_advice",
    "dangerous_methods",
    "treatment_guarantee",
    "dependency_reinforcement",
    "unverified_resources",
]


def _text(state: Mapping[str, Any]) -> str:
    return str(state.get("normalized_text") or state.get("user_text") or "")


def _semantic(state: Mapping[str, Any]) -> dict[str, Any]:
    value = state.get("semantic_risk")
    return dict(value) if isinstance(value, Mapping) else {}


def _has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def derive_risk_domain(state: Mapping[str, Any]) -> str:
    category = str(state.get("control_category") or "")
    if category in DOMAIN_BY_CATEGORY:
        return DOMAIN_BY_CATEGORY[category]
    if str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS:
        return "self_harm"
    return "normal_support"


def derive_immediacy(state: Mapping[str, Any]) -> str:
    semantic = _semantic(state)
    text = _text(state)
    if semantic.get("timeframe") == "near_term" or semantic.get("means") or semantic.get("plan"):
        return "near_term"
    if _has_any(text, ("正在", "已经", "现在就", "马上", "立刻", "right now")):
        return "active"
    if str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS:
        return "vague"
    return "none"


def derive_protective_signals(state: Mapping[str, Any]) -> list[str]:
    semantic = _semantic(state)
    text = _text(state)
    signals: list[str] = []
    if text.strip():
        signals.append("still_talking")
    if semantic.get("protective_factor"):
        signals.append("protective_factor")
    if _has_any(text, ("不会做", "不会真的", "暂时不会", "我还在", "没事", "有人陪", "朋友", "家人", "室友", "老师")):
        signals.append("verbal_safety_or_support")
    if _has_any(text, ("帮帮我", "陪我", "不知道怎么办", "救救我", "help")):
        signals.append("asks_for_help")
    return list(dict.fromkeys(signals))


def derive_risk_phase(state: Mapping[str, Any]) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    text = _text(state)
    recent = state.get("recent_messages")
    recent_count = len(recent) if isinstance(recent, list) else 0
    protective = derive_protective_signals(state)
    if risk_level not in HIGH_RISK_LEVELS:
        return "post_crisis" if recent_count and _has_any(text, ("好多了", "缓过来了", "没那么强了")) else "first_contact"
    if "verbal_safety_or_support" in protective and recent_count >= 1:
        return "deescalating"
    if recent_count >= 2:
        return "still_high"
    return "first_contact"


def risk_confidence_for_state(state: Mapping[str, Any]) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    confidence = float(state.get("control_confidence") or 0.0)
    if risk_level in {"L2", "L3"} or confidence >= 0.85:
        return "high"
    if confidence >= 0.65 or risk_level == "L1":
        return "medium"
    return "low"


def length_profile_for_state(state: Mapping[str, Any], *, domain: str, immediacy: str, phase: str) -> str:
    risk_level = str(state.get("risk_level") or "L0")
    text = _text(state)
    if domain in {"medical_request", "prompt_attack", "sexual_boundary"}:
        return "firm_brief"
    if _has_any(text, ("多陪我", "讲点什么", "多说一点", "别停", "陪我说")):
        return "holding_longer"
    if risk_level == "L3" and phase == "first_contact" and immediacy in {"near_term", "active"}:
        return "brief_first_contact"
    if risk_level in HIGH_RISK_LEVELS and phase == "still_high":
        return "steady_short"
    if risk_level in HIGH_RISK_LEVELS and phase in {"deescalating", "post_crisis"}:
        return "warm_medium"
    if risk_level == "L1":
        return "supportive_medium"
    return "warm_medium" if domain != "normal_support" else "supportive_medium"


def build_risk_response_policy(state: Mapping[str, Any]) -> dict[str, Any]:
    domain = derive_risk_domain(state)
    immediacy = derive_immediacy(state)
    phase = derive_risk_phase(state)
    length_profile = length_profile_for_state(state, domain=domain, immediacy=immediacy, phase=phase)
    forbidden_moves = list(BASE_FORBIDDEN_MOVES)
    allowed_moves = ["brief_validation", "one_question_or_none"]
    if domain == "self_harm":
        allowed_moves = ["brief_validation", "time_box", "micro_safety_step", "one_low_friction_reply"]
        forbidden_moves += ["method_detail", "professional_referral_first_turn", "moralizing", "empty_reassurance"]
    elif domain == "harm_other":
        allowed_moves = ["brief_validation", "deescalate_impulse", "increase_distance_from_target", "return_to_feelings"]
        forbidden_moves += ["revenge_validation", "attack_instruction"]
    elif domain == "clinical_red_flag":
        allowed_moves = ["brief_validation", "ground_in_reality", "trusted_person_support"]
        forbidden_moves += ["delusion_confirmation", "diagnostic_label"]
    elif domain == "medical_request":
        allowed_moves = ["brief_boundary", "symptom_organization", "prepare_professional_questions"]
        forbidden_moves += ["medication_or_dosage_advice", "stop_medication_advice"]
    elif domain == "dependency":
        allowed_moves = ["warm_presence", "avoid_exclusive_support", "expand_support_gently"]
        forbidden_moves += ["exclusive_attachment", "forever_available_promise"]
    elif domain in {"sexual_boundary", "prompt_attack"}:
        allowed_moves = ["brief_boundary", "safe_alternative"]
    return {
        "risk_domain": domain,
        "immediacy": immediacy,
        "risk_confidence": risk_confidence_for_state(state),
        "protective_signals": derive_protective_signals(state),
        "risk_phase": phase,
        "allowed_moves": allowed_moves,
        "forbidden_moves": list(dict.fromkeys(forbidden_moves)),
        "tone": "low_pressure" if domain in {"self_harm", "victimization", "clinical_red_flag"} else "calm_boundary",
        "max_questions": 1,
        "length_profile": length_profile,
        "char_budget": dict(LENGTH_BUDGETS[length_profile]),
    }


def default_actions_for_policy(policy: Mapping[str, Any]) -> list[str]:
    domain = str(policy.get("risk_domain") or "normal_support")
    immediacy = str(policy.get("immediacy") or "none")
    phase = str(policy.get("risk_phase") or "first_contact")
    if domain == "self_harm" and immediacy in {"near_term", "active"}:
        return ["我还在", "我退开一点了", "我身边有人", "请继续跟我说"]
    if domain == "self_harm":
        return ["我还在", "先陪我一分钟", "我先不动", "我说不出来"]
    if domain == "harm_other":
        return ["我先离远一点", "我现在很气", "先别让我做决定", "继续跟我说"]
    if domain == "clinical_red_flag":
        return ["我现在有点害怕", "先帮我稳住", "我能找谁"]
    if domain == "dependency":
        return ["我怕没人懂", "我不知道能找谁", "我还想说一点"]
    if domain == "medical_request":
        return ["我想整理症状", "我有点担心", "先帮我理清问题"]
    if domain in {"sexual_boundary", "prompt_attack"}:
        return ["我其实有点烦", "先随便聊聊", "我想说这块"]
    if phase == "deescalating":
        return ["我好一点了", "还想说一点", "先慢慢来"]
    return ["我想慢慢说", "先帮我稳一下", "我不知道原因"]


def tool_gate_mode_for_state(state: Mapping[str, Any]) -> str:
    category = str(state.get("control_category") or "")
    if category in BLOCKED_CONTEXT_CATEGORIES:
        return "blocked_context"
    if str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS:
        return "safety_context"
    return "normal_context"
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_risk_policy.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/risk_policy.py backend/tests/test_risk_policy.py
git commit -m "feat: add backend risk policy service"
```

---

### Task 2: Expose Policy Fields From Control Plane

**Files:**
- Modify: `backend/app/graphs/state.py`
- Modify: `backend/app/graphs/nodes/control_nodes.py`
- Test: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Write failing control-plane tests**

Add these tests to `ConversationControlRagTests` in `backend/tests/test_conversation_control_rag.py`:

```python
    def test_control_plane_adds_risk_policy_fields_for_l3(self) -> None:
        state = self.make_state(
            "我今晚想自杀，药就在手里",
            risk_level="L3",
            semantic_risk={"ideation": True, "means": True, "timeframe": "near_term"},
            risk_reason_codes=["explicit_ideation", "means_mentioned"],
        )

        result = _run(control_plane(state))

        self.assertEqual(result["risk_domain"], "self_harm")
        self.assertEqual(result["immediacy"], "near_term")
        self.assertEqual(result["risk_phase"], "first_contact")
        self.assertEqual(result["risk_response_policy"]["length_profile"], "brief_first_contact")
        self.assertEqual(result["tool_gate_mode"], "safety_context")
        self.assertIn("micro_safety_step", result["risk_response_policy"]["allowed_moves"])

    def test_control_plane_maps_medical_request_to_blocked_context(self) -> None:
        state = self.make_state("我能不能自己停药，剂量怎么调")

        result = _run(control_plane(state))

        self.assertEqual(result["control_category"], "diagnosis_or_medical_request")
        self.assertEqual(result["risk_domain"], "medical_request")
        self.assertEqual(result["tool_gate_mode"], "blocked_context")
        self.assertEqual(result["risk_response_policy"]["length_profile"], "firm_brief")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_control_plane_adds_risk_policy_fields_for_l3 tests/test_conversation_control_rag.py::ConversationControlRagTests::test_control_plane_maps_medical_request_to_blocked_context -v
```

Expected: FAIL with missing keys such as `risk_domain` or `risk_response_policy`.

- [ ] **Step 3: Extend `AgentState`**

In `backend/app/graphs/state.py`, add these fields after `requires_safety_check`:

```python
    risk_domain: str
    immediacy: Literal["none", "vague", "near_term", "active"]
    risk_confidence: Literal["low", "medium", "high"]
    protective_signals: list[str]
    risk_phase: Literal["first_contact", "stabilizing", "still_high", "deescalating", "post_crisis"]
    risk_response_policy: dict
    tool_gate_mode: Literal["normal_context", "safety_context", "blocked_context"]
    safety_context_pack: dict
    experience_validator_reasons: list[str]
```

- [ ] **Step 4: Wire policy into `control_plane`**

In `backend/app/graphs/nodes/control_nodes.py`, add imports:

```python
from app.services.risk_policy import build_risk_response_policy, tool_gate_mode_for_state
```

Near the end of `control_plane`, immediately before the final `return`, insert:

```python
    policy_state = {
        **state,
        "risk_level": risk_level,
        "control_category": category,
        "control_confidence": confidence,
        "semantic_risk": semantic_risk,
        "normalized_text": text,
        "risk_reason_codes": risk_reason_codes,
        "recent_messages": state.get("recent_messages", []),
    }
    risk_response_policy = build_risk_response_policy(policy_state)
    tool_gate_mode = tool_gate_mode_for_state(
        {
            "risk_level": risk_level,
            "control_category": category,
        }
    )
```

Add these keys to the returned dict:

```python
        "risk_domain": risk_response_policy["risk_domain"],
        "immediacy": risk_response_policy["immediacy"],
        "risk_confidence": risk_response_policy["risk_confidence"],
        "protective_signals": risk_response_policy["protective_signals"],
        "risk_phase": risk_response_policy["risk_phase"],
        "risk_response_policy": risk_response_policy,
        "tool_gate_mode": tool_gate_mode,
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_risk_policy.py tests/test_conversation_control_rag.py::ConversationControlRagTests::test_control_plane_adds_risk_policy_fields_for_l3 tests/test_conversation_control_rag.py::ConversationControlRagTests::test_control_plane_maps_medical_request_to_blocked_context -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/graphs/state.py backend/app/graphs/nodes/control_nodes.py backend/tests/test_conversation_control_rag.py
git commit -m "feat: expose risk response policy from control plane"
```

---

### Task 3: Build Safety Context Pack

**Files:**
- Create: `backend/app/services/safety_context_service.py`
- Create: `backend/tests/test_safety_context_service.py`
- Modify: `backend/app/services/memory_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/graph_runtime.py`

- [ ] **Step 1: Write failing tests for safety context sanitization**

Create `backend/tests/test_safety_context_service.py`:

```python
from __future__ import annotations

import unittest

from app.services.safety_context_service import build_safety_context_pack, sanitize_safety_context_text


class SafetyContextServiceTests(unittest.TestCase):
    def test_sanitize_filters_contacts_and_method_details(self) -> None:
        text = "用户之前说刀在床边，手机号 138 0000 0000，姐姐能陪。"

        sanitized = sanitize_safety_context_text(text, risk_level="L3")

        self.assertNotIn("刀", sanitized)
        self.assertNotIn("138", sanitized)
        self.assertIn("姐姐", sanitized)
        self.assertIn("已概括安全风险细节", sanitized)

    def test_pack_keeps_safe_memory_types_only(self) -> None:
        pack = build_safety_context_pack(
            risk_level="L3",
            retrieved_memories=[
                {
                    "memory_type": "preference",
                    "summary": "用户不喜欢被命令，偏好短句。",
                    "visibility": "user_visible",
                },
                {
                    "memory_type": "relationship",
                    "content": "姐姐可以陪用户一会儿，电话 13800000000。",
                    "visibility": "user_visible",
                },
                {
                    "memory_type": "state",
                    "content": "普通状态记忆不应进入高风险安全包。",
                    "visibility": "user_visible",
                },
            ],
            session_digest={"summary_200chars": "最近夜间孤独时风险升高。"},
            user_context_pack={"style_corrections": ["不要一上来推热线"]},
        )

        self.assertEqual(pack["schema_version"], 1)
        self.assertIn("不要一上来推热线", pack["style_corrections"])
        self.assertTrue(any("不喜欢被命令" in item for item in pack["memory_hints"]))
        self.assertTrue(any("姐姐" in item for item in pack["support_hints"]))
        self.assertFalse(any("普通状态记忆" in item for item in pack["memory_hints"]))
        self.assertNotIn("138", str(pack))

    def test_low_risk_pack_is_empty(self) -> None:
        pack = build_safety_context_pack(
            risk_level="L1",
            retrieved_memories=[{"memory_type": "preference", "summary": "偏好短句"}],
            session_digest={},
            user_context_pack={},
        )

        self.assertEqual(pack, {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_safety_context_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.safety_context_service'`.

- [ ] **Step 3: Implement safety context service**

Create `backend/app/services/safety_context_service.py`:

```python
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


HIGH_RISK_LEVELS = {"L2", "L3"}
SAFETY_CONTEXT_MEMORY_TYPES = {"safety_summary", "support_strategy", "preference", "correction", "relationship"}
SUPPORT_MEMORY_TYPES = {"relationship", "safety_summary"}
HIGH_RISK_DETAIL_TERMS = (
    "刀",
    "药",
    "跳楼",
    "楼顶",
    "绳",
    "煤气",
    "割腕",
    "安眠药",
    "pills",
    "knife",
    "roof",
    "bridge",
)


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _append_unique(items: list[str], value: object, *, limit: int = 5, item_limit: int = 120) -> None:
    text = _compact(value)
    if not text:
        return
    if len(text) > item_limit:
        text = text[:item_limit].rstrip()
    if text in items:
        return
    items.append(text)
    if len(items) > limit:
        del items[limit:]


def sanitize_safety_context_text(text: object, *, risk_level: str) -> str:
    sanitized = _compact(text)
    sanitized = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[已过滤联系方式]", sanitized)
    sanitized = re.sub(r"(?<!\d)\d[\d\s-]{6,}\d(?!\d)", "[已过滤联系方式]", sanitized)
    if risk_level in HIGH_RISK_LEVELS:
        for term in HIGH_RISK_DETAIL_TERMS:
            sanitized = re.sub(re.escape(term), "[已概括安全风险细节]", sanitized, flags=re.IGNORECASE)
    return sanitized


def _memory_text(memory: Mapping[str, Any], *, risk_level: str) -> str:
    value = memory.get("summary") or memory.get("description") or memory.get("content") or memory.get("title") or ""
    return sanitize_safety_context_text(value, risk_level=risk_level)


def build_safety_context_pack(
    *,
    risk_level: str,
    retrieved_memories: list[dict[str, Any]] | None,
    session_digest: Mapping[str, Any] | None,
    user_context_pack: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if risk_level not in HIGH_RISK_LEVELS:
        return {}

    memory_hints: list[str] = []
    support_hints: list[str] = []
    style_corrections: list[str] = []
    continuity_notes: list[str] = []

    for raw in retrieved_memories or []:
        if not isinstance(raw, Mapping):
            continue
        memory_type = str(raw.get("memory_type") or "")
        if memory_type not in SAFETY_CONTEXT_MEMORY_TYPES:
            continue
        text = _memory_text(raw, risk_level=risk_level)
        if not text:
            continue
        if memory_type in SUPPORT_MEMORY_TYPES:
            _append_unique(support_hints, text)
        else:
            _append_unique(memory_hints, text)

    if isinstance(user_context_pack, Mapping):
        for item in user_context_pack.get("style_corrections") or []:
            _append_unique(style_corrections, sanitize_safety_context_text(item, risk_level=risk_level))

    if isinstance(session_digest, Mapping):
        summary = sanitize_safety_context_text(session_digest.get("summary_200chars"), risk_level=risk_level)
        if summary:
            _append_unique(continuity_notes, summary)

    return {
        "schema_version": 1,
        "risk_level": risk_level,
        "memory_hints": memory_hints,
        "support_hints": support_hints,
        "style_corrections": style_corrections,
        "continuity_notes": continuity_notes,
    }
```

- [ ] **Step 4: Allow high-risk safety memory types**

In `backend/app/services/memory_service.py`, modify `retrieve_memories_for_turn()` high-risk allowed types:

```python
    include_internal = risk_level in {"L2", "L3"}
    allowed_types = _allowed_memory_types_for_mode(memory_mode, include_internal=include_internal)
    if include_internal:
        allowed_types = {"safety_summary", "support_strategy", "preference", "correction", "relationship"}
```

Modify `_memory_visible_for_turn()` to allow those safe types in high-risk mode:

```python
def _memory_visible_for_turn(memory: UserMemory, *, allowed_types: set[str], risk_level: str) -> bool:
    if memory.memory_type not in allowed_types:
        return False
    if risk_level in {"L2", "L3"}:
        if memory.memory_type == "safety_summary":
            return memory.visibility == "internal_safety"
        return memory.visibility == "user_visible" and memory.memory_type in {
            "support_strategy",
            "preference",
            "correction",
            "relationship",
        }
    return memory.visibility == "user_visible"
```

- [ ] **Step 5: Build safety context in chat preparation**

In `backend/app/services/chat_service.py`, add import:

```python
from app.services.safety_context_service import build_safety_context_pack
```

After the existing `user_context_pack = build_user_context_pack(` assignment block in `_prepare_turn_context()`, insert:

```python
    safety_context_pack = build_safety_context_pack(
        risk_level=pre_risk_level,
        retrieved_memories=retrieved_memories,
        session_digest=thread.session_digest or {},
        user_context_pack=user_context_pack,
    )
    if safety_context_pack:
        user_context_pack = {
            **user_context_pack,
            "safety_context_pack": safety_context_pack,
        }
```

- [ ] **Step 6: Carry safety context through runtime**

In `backend/app/services/graph_runtime.py`, add `safety_context_pack` to `_build_input_state()` signature:

```python
        safety_context_pack: dict | None = None,
```

Add it to the returned state:

```python
            "safety_context_pack": safety_context_pack or {},
```

Add the same argument to `invoke_turn()` and `stream_turn()` signatures and forward it into `_build_input_state()`.

In `chat_service._invoke_graph_with_fallback()` and streaming graph call, pass:

```python
                safety_context_pack=user_context_pack.get("safety_context_pack", {}) if isinstance(user_context_pack, dict) else {},
```

- [ ] **Step 7: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_safety_context_service.py tests/test_user_context_pack_service.py tests/test_graph_runtime_streaming.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/safety_context_service.py backend/tests/test_safety_context_service.py backend/app/services/memory_service.py backend/app/services/chat_service.py backend/app/services/graph_runtime.py
git commit -m "feat: add high-risk safety context pack"
```

---

### Task 4: Add Safety Tool Gate Mode

**Files:**
- Modify: `backend/app/services/tooling.py`
- Modify: `backend/tests/test_tooling.py`

- [ ] **Step 1: Write failing tool gate tests**

Update imports in `backend/tests/test_tooling.py`:

```python
from app.services.tooling import ALL_RISK_LEVELS, LOW_RISK_LEVELS, TOOL_SPEC_BY_NAME, ToolGate, build_dialogue_tool_plan, summarize_tool_events
```

Add these tests to `ToolGateTests`:

```python
    def test_high_risk_plan_exposes_safety_context_tools(self) -> None:
        plan = build_dialogue_tool_plan(make_state(risk_level="L2"))

        self.assertEqual(
            [tool["function"]["name"] for tool in plan.tools],
            ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"],
        )
        self.assertEqual(plan.allowed_tool_names, ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"])
        self.assertIn("save_memory_summary", plan.blocked_tool_names)
        self.assertIn("web_search", plan.blocked_tool_names)
        self.assertIn("get_weather", plan.blocked_tool_names)

    def test_blocked_context_keeps_only_minimal_tools(self) -> None:
        state = make_state(risk_level="L1")
        state["tool_gate_mode"] = "blocked_context"

        plan = build_dialogue_tool_plan(state)

        self.assertEqual([tool["function"]["name"] for tool in plan.tools], ["get_current_time", "summarize_session"])
```

Add this test to `MemoryToolHandlerTests`:

```python
    def test_high_risk_search_memories_returns_safe_context_only(self) -> None:
        state = make_state(
            risk_level="L3",
            memory_index=[
                {
                    "memory_id": "pref-1",
                    "memory_type": "preference",
                    "title": "Style",
                    "description": "User dislikes command-like replies.",
                    "importance": 4,
                    "visibility": "user_visible",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
                {
                    "memory_id": "state-1",
                    "memory_type": "state",
                    "title": "Ordinary state",
                    "description": "Should not show in safety context.",
                    "importance": 4,
                    "visibility": "user_visible",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "freshness_warning": "",
                },
            ],
        )
        state["tool_gate_mode"] = "safety_context"
        plan = build_dialogue_tool_plan(state)

        result = plan.tool_handlers["search_memories"]({"query": "style", "limit": 5})

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["memory_id"], "pref-1")
        self.assertNotIn("state-1", str(result))
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_tooling.py::ToolGateTests::test_high_risk_plan_exposes_safety_context_tools tests/test_tooling.py::ToolGateTests::test_blocked_context_keeps_only_minimal_tools tests/test_tooling.py::MemoryToolHandlerTests::test_high_risk_search_memories_returns_safe_context_only -v
```

Expected: FAIL because high-risk plans still expose only safety resources/time/summary and `safe_web_search` does not exist.

- [ ] **Step 3: Add safety tool constants and spec**

In `backend/app/services/tooling.py`, add:

```python
SAFETY_CONTEXT_MEMORY_TYPES = frozenset({"safety_summary", "support_strategy", "preference", "correction", "relationship"})
SAFETY_CONTEXT_TOOL_NAMES = frozenset({"search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"})
BLOCKED_CONTEXT_TOOL_NAMES = frozenset({"get_current_time", "summarize_session"})
```

Add a `ToolSpec` after `web_search`:

```python
    ToolSpec(
        name="safe_web_search",
        description="Search only trusted public support resources without including user personal details or unsafe method terms.",
        allowed_risk_levels=ALL_RISK_LEVELS,
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Short region code or location hint, for example CN or US.",
                },
                "audience": {
                    "type": "string",
                    "enum": ["all", "teen", "adult"],
                    "description": "Use teen for minors, adult for adults, all if unknown.",
                },
            },
            "additionalProperties": False,
        },
    ),
```

- [ ] **Step 4: Update `ToolGate`**

Add `tool_gate_mode` to the dataclass:

```python
    tool_gate_mode: str = "normal_context"
```

Update `allowed_tool_names()`:

```python
    def allowed_tool_names(self) -> list[str]:
        if self.tool_gate_mode == "blocked_context":
            return [name for name in ["get_current_time", "summarize_session"] if self.allows(name)]
        if self.tool_gate_mode == "safety_context" or self.risk_level in HIGH_RISK_LEVELS:
            return [name for name in ["search_memories", "get_safety_resources", "safe_web_search", "get_current_time", "summarize_session"] if self.allows(name)]
        names = []
        if self.memory_mode != "off":
            names.extend(["search_memories", "save_memory_summary"])
        names.append("get_safety_resources")
        names.append("web_search")
        names.append("get_current_time")
        names.append("get_weather")
        names.append("summarize_session")
        if self.knowledge_enabled:
            names.append("ask_knowledge")
        return [name for name in names if self.allows(name)]
```

Update `allows()` high-risk branch:

```python
        if self.tool_gate_mode == "blocked_context":
            return name in BLOCKED_CONTEXT_TOOL_NAMES
        if self.tool_gate_mode == "safety_context" or self.risk_level in HIGH_RISK_LEVELS:
            return name in SAFETY_CONTEXT_TOOL_NAMES
```

Update `build_dialogue_tool_plan()` gate construction:

```python
        tool_gate_mode=str(state.get("tool_gate_mode") or "normal_context"),
```

- [ ] **Step 5: Filter memory handler in safety context**

In `_search_memory_entries()`, add a parameter:

```python
    safety_context: bool = False,
```

Inside the loop over entries, before scoring:

```python
        if safety_context and str(entry.get("memory_type") or "") not in SAFETY_CONTEXT_MEMORY_TYPES:
            continue
        if safety_context and str(entry.get("visibility") or "user_visible") not in {"user_visible", "internal_safety"}:
            continue
```

In `_build_search_memories_handler()`, set:

```python
        safety_context = str(state.get("tool_gate_mode") or "") == "safety_context" or str(state.get("risk_level") or "L0") in HIGH_RISK_LEVELS
```

Pass `safety_context=safety_context` into `_search_memory_entries()`.

- [ ] **Step 6: Add safe web search handler**

Add this handler factory near `_build_web_search_handler()`:

```python
def _build_safe_web_search_handler(state: Mapping[str, Any], capture: ToolAuditCapture) -> ToolHandler:
    def safe_web_search(arguments: dict[str, Any]) -> dict[str, Any]:
        region = _clean_text(arguments.get("region") or state.get("crisis_resource_region") or "CN", limit=24) or "CN"
        audience = _coerce_audience(arguments.get("audience"), fallback="teen" if state.get("user_mode") == "teen" else "all")
        query = f"{region} mental health crisis support resources {audience.value}"
        try:
            from app.services.search_service import search_web

            results = search_web(query, max_results=3)
        except Exception as exc:
            capture.record_preview("safe_web_search", status="error", error=type(exc).__name__)
            return {"query": query, "items": [], "status": "error"}
        items = [
            {
                "title": _clean_text(item.get("title"), limit=100),
                "url": _clean_text(item.get("url"), limit=240),
                "snippet": _clean_text(item.get("snippet"), limit=180),
            }
            for item in results
            if isinstance(item, dict)
        ]
        capture.record_preview("safe_web_search", status="completed", preview={"query": query, "count": len(items)})
        return {"query": query, "items": items, "status": "completed"}

    return safe_web_search
```

In `build_dialogue_tool_plan()`, register it:

```python
    if "safe_web_search" in allowed_names:
        handlers["safe_web_search"] = _build_safe_web_search_handler(state, capture)
```

Update `_tool_prompt_hint()` descriptions:

```python
        "safe_web_search": "safe_web_search: search trusted public support resources using backend-generated queries; never include user personal details or unsafe method terms.",
```

- [ ] **Step 7: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_tooling.py::ToolGateTests tests/test_tooling.py::MemoryToolHandlerTests -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/tooling.py backend/tests/test_tooling.py
git commit -m "feat: add safety context tool gate"
```

---

### Task 5: Generate Policy-Based Risk Replies

**Files:**
- Modify: `backend/app/graphs/nodes/response_nodes.py`
- Modify: `backend/tests/test_conversation_control_rag.py`
- Modify: `backend/tests/test_safety_evaluation.py`

- [ ] **Step 1: Write failing response tests**

Add tests to `ConversationControlRagTests`:

```python
    def test_l3_crisis_response_is_low_pressure_without_method_repetition(self) -> None:
        state = self.make_state(
            "我现在想自杀，刀在手里",
            risk_level="L3",
            control_category="self_harm_risk",
            risk_domain="self_harm",
            immediacy="near_term",
            risk_phase="first_contact",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "near_term",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
        )

        from app.graphs.nodes.response_nodes import crisis_response

        result = _run(crisis_response(state))
        text = result["assistant_text"]

        self.assertIn("这一分钟", text)
        self.assertIn("回我一个字", text)
        self.assertNotIn("刀", text)
        self.assertNotIn("心理咨询师", text)
        self.assertNotIn("精神科", text)
        self.assertNotIn("医院心理门诊", text)
        self.assertNotIn("接住", text)
        self.assertLessEqual(len(text), 360)

    def test_l2_crisis_response_uses_medium_length_when_user_asks_for_more(self) -> None:
        state = self.make_state(
            "我想死，但你多陪我说说",
            risk_level="L2",
            control_category="self_harm_risk",
            risk_domain="self_harm",
            immediacy="vague",
            risk_phase="deescalating",
            risk_response_policy={
                "risk_domain": "self_harm",
                "immediacy": "vague",
                "risk_phase": "deescalating",
                "length_profile": "holding_longer",
                "char_budget": {"target": 700, "max": 980},
            },
        )

        from app.graphs.nodes.response_nodes import crisis_response

        result = _run(crisis_response(state))
        text = result["assistant_text"]

        self.assertGreaterEqual(len(text), 180)
        self.assertNotIn("珍惜生命", text)
        self.assertNotIn("世界还有很多美好", text)
        self.assertNotIn("接住", text)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_l3_crisis_response_is_low_pressure_without_method_repetition tests/test_conversation_control_rag.py::ConversationControlRagTests::test_l2_crisis_response_uses_medium_length_when_user_asks_for_more -v
```

Expected: FAIL because current crisis response includes static emergency wording and does not respect `risk_response_policy`.

- [ ] **Step 3: Add policy-based reply helpers**

In `backend/app/graphs/nodes/response_nodes.py`, add import:

```python
from app.services.risk_policy import build_risk_response_policy, default_actions_for_policy
```

Add helper functions above `crisis_response()`:

```python
def _policy_for_state(state: AgentState) -> dict:
    policy = state.get("risk_response_policy")
    if isinstance(policy, dict) and policy:
        return policy
    return build_risk_response_policy(state)


def _self_harm_first_contact_text(policy: dict, *, teen_mode: bool) -> str:
    if teen_mode:
        return (
            "你现在已经痛到很难再撑了。我们先不讲以后，也不急着分析原因，只先把这一分钟过掉。"
            "你能不能先让那个东西离你远一点，或者从那个位置退一步？"
            "不用解释，回我一个字也可以。"
        )
    return (
        "你现在已经痛到很难再撑了。我们先不讲以后，也不分析原因，只先把这一分钟过掉。"
        "你能不能先让那个东西离你远一点，或者从那个位置退一步？"
        "回我一个字也可以。"
    )


def _self_harm_steady_text(policy: dict, *, teen_mode: bool) -> str:
    if policy.get("length_profile") == "holding_longer":
        return (
            "好，我们先不把你推去任何地方，也不急着说大道理。我会跟你待在这一小段里。"
            "这种冲动像一阵很高的浪，浪最高的时候，人很容易觉得只有一个出口。"
            "但我们现在不需要证明以后会怎样，只要先别在浪最高的时候做决定。"
            "你可以慢慢回我：这一刻最压着你的，是孤独、委屈、累，还是一种说不出来的空？"
        )
    return (
        "我还在。我们继续把范围缩小一点，不急着解释全部原因。"
        "你先确认一件很小的事：现在能不能让自己离那个动作再远一点，哪怕只是坐下来、停十秒、回我一个字。"
    )


def _self_harm_reply_for_policy(policy: dict, *, teen_mode: bool) -> str:
    phase = str(policy.get("risk_phase") or "first_contact")
    immediacy = str(policy.get("immediacy") or "vague")
    if phase == "first_contact" and immediacy in {"near_term", "active"}:
        return _self_harm_first_contact_text(policy, teen_mode=teen_mode)
    return _self_harm_steady_text(policy, teen_mode=teen_mode)
```

- [ ] **Step 4: Replace `crisis_response()`**

Replace the body of `crisis_response()` with:

```python
async def crisis_response(state: AgentState) -> AgentState:
    teen_mode = state.get("profile", {}).get("user_mode", state.get("user_mode", "adult")) == "teen"
    policy = _policy_for_state(state)
    domain = str(policy.get("risk_domain") or "self_harm")
    if domain == "self_harm":
        assistant_text = _self_harm_reply_for_policy(policy, teen_mode=teen_mode)
        actions = default_actions_for_policy(policy)
        return {
            "assistant_text": assistant_text,
            "suggested_actions": actions,
            "risk_response_policy": policy,
        }
    assistant_text = "我在。我们先把这一刻放慢一点，不急着做决定，也不往危险方向走。你可以只说现在最强的感觉是什么。"
    return {
        "assistant_text": assistant_text,
        "suggested_actions": default_actions_for_policy(policy),
        "risk_response_policy": policy,
    }
```

- [ ] **Step 5: Adjust older expectations**

In `backend/tests/test_safety_evaluation.py`, update tests that expect L2 to mention professional help or L3 emergency numbers in the first reply. Replace assertions such as:

```python
self.assertIn("专业", text)
self.assertIn("120", text)
self.assertIn("110", text)
```

with:

```python
self.assertIn("这一分钟", text)
self.assertNotIn("精神科", text)
self.assertNotIn("医院心理门诊", text)
self.assertNotIn("珍惜生命", text)
```

For teen L3 tests, keep the assertion that teen responses do not encourage isolation, but do not require the first suggested action to be `拨打`.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
cd backend
python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_l3_crisis_response_is_low_pressure_without_method_repetition tests/test_conversation_control_rag.py::ConversationControlRagTests::test_l2_crisis_response_uses_medium_length_when_user_asks_for_more tests/test_safety_evaluation.py::L2GentleCrisisResponseTests -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/graphs/nodes/response_nodes.py backend/tests/test_conversation_control_rag.py backend/tests/test_safety_evaluation.py
git commit -m "feat: make crisis replies policy based"
```

---

### Task 6: Add Experience Validator

**Files:**
- Modify: `backend/app/graphs/nodes/validator_nodes.py`
- Modify: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Write failing validator tests**

Add these tests to `ConversationControlRagTests`:

```python
    def test_experience_validator_blocks_banned_phrase(self) -> None:
        state = self.make_state(
            "我很难受",
            risk_level="L1",
            assistant_text="我会接住你的情绪，我们慢慢说。",
            suggested_actions=[],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("banned_phrase:接住", result["experience_validator_reasons"])

    def test_experience_validator_blocks_first_turn_professional_referral(self) -> None:
        state = self.make_state(
            "我想死",
            risk_level="L2",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 220, "max": 360},
            },
            assistant_text="我建议你尽快找专业心理咨询师或者精神科聊聊。",
            suggested_actions=["找心理咨询师"],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("professional_referral_first_turn", result["experience_validator_reasons"])
        self.assertEqual(result["delivery_status"], "safety_fallback")

    def test_experience_validator_checks_length_profile(self) -> None:
        state = self.make_state(
            "我现在很危险",
            risk_level="L3",
            route_priority="P0_immediate_safety",
            control_category="self_harm_risk",
            risk_response_policy={
                "risk_domain": "self_harm",
                "risk_phase": "first_contact",
                "length_profile": "brief_first_contact",
                "char_budget": {"target": 120, "max": 140},
            },
            assistant_text="我在。" * 100,
            suggested_actions=[],
        )

        result = _run(response_validator(state))

        self.assertTrue(result["validator_blocked"])
        self.assertIn("length_budget_exceeded", result["experience_validator_reasons"])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_blocks_banned_phrase tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_blocks_first_turn_professional_referral tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_checks_length_profile -v
```

Expected: FAIL because `experience_validator_reasons` is not implemented.

- [ ] **Step 3: Implement experience validator**

In `backend/app/graphs/nodes/validator_nodes.py`, add constants:

```python
EXPERIENCE_BANNED_TERMS = ("接住",)
MORALIZING_TERMS = ("珍惜生命", "世界还有很多美好", "想想你的家人")
FIRST_TURN_REFERRAL_TERMS = ("心理咨询师", "精神科", "医院心理门诊", "尽快就医")
```

Add function:

```python
def experience_validator_reasons(text: str, actions: list[str], state: AgentState) -> list[str]:
    reasons: list[str] = []
    for term in EXPERIENCE_BANNED_TERMS:
        if term in text or any(term in action for action in actions):
            reasons.append(f"banned_phrase:{term}")
    if any(term in text for term in MORALIZING_TERMS):
        reasons.append("moralizing_reassurance")
    policy = state.get("risk_response_policy") if isinstance(state.get("risk_response_policy"), dict) else {}
    risk_level = state.get("risk_level", "L0")
    if risk_level in {"L2", "L3"} and str(policy.get("risk_phase") or "first_contact") == "first_contact":
        if any(term in text for term in FIRST_TURN_REFERRAL_TERMS) or any(
            any(term in action for term in FIRST_TURN_REFERRAL_TERMS) for action in actions
        ):
            reasons.append("professional_referral_first_turn")
    budget = policy.get("char_budget") if isinstance(policy, dict) else {}
    max_chars = budget.get("max") if isinstance(budget, dict) else None
    if isinstance(max_chars, int) and len(text) > max_chars:
        reasons.append("length_budget_exceeded")
    if text.count("？") + text.count("?") > int(policy.get("max_questions", 1) if isinstance(policy, dict) else 1):
        reasons.append("too_many_questions")
    return sorted(set(reasons))
```

In `response_validator()`, after the existing `validator_reasons` call assigns `reasons`, add:

```python
    experience_reasons = experience_validator_reasons(assistant_text, actions, state)
    reasons = sorted(set(reasons + experience_reasons))
```

In all return dicts from `response_validator()`, add:

```python
                "experience_validator_reasons": experience_reasons,
```

For branches that currently return `validator_reasons: []`, set `experience_validator_reasons` to `[]`.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_blocks_banned_phrase tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_blocks_first_turn_professional_referral tests/test_conversation_control_rag.py::ConversationControlRagTests::test_experience_validator_checks_length_profile -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/graphs/nodes/validator_nodes.py backend/tests/test_conversation_control_rag.py
git commit -m "feat: add experience safety validator"
```

---

### Task 7: Persist and Stream Policy Metadata

**Files:**
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/tests/test_graph_runtime_streaming.py`
- Modify: `backend/tests/test_chat_idempotency.py`

- [ ] **Step 1: Write failing runtime mapping test**

Add to `backend/tests/test_graph_runtime_streaming.py`:

```python
def test_map_result_includes_risk_policy_metadata() -> None:
    from app.services.graph_runtime import GraphRuntime

    runtime = object.__new__(GraphRuntime)
    result = runtime._map_result(
        {
            "assistant_text": "我在。",
            "risk_level": "L3",
            "risk_domain": "self_harm",
            "immediacy": "near_term",
            "risk_confidence": "high",
            "protective_signals": ["still_talking"],
            "risk_phase": "first_contact",
            "risk_response_policy": {"length_profile": "brief_first_contact"},
            "tool_gate_mode": "safety_context",
            "safety_context_pack": {"schema_version": 1},
            "experience_validator_reasons": [],
            "delivery_status": "generated",
        },
        retrieved_memories=[],
    )

    self.assertEqual(result["risk_domain"], "self_harm")
    self.assertEqual(result["immediacy"], "near_term")
    self.assertEqual(result["risk_phase"], "first_contact")
    self.assertEqual(result["tool_gate_mode"], "safety_context")
    self.assertEqual(result["risk_response_policy"]["length_profile"], "brief_first_contact")
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
cd backend
python -m pytest tests/test_graph_runtime_streaming.py::test_map_result_includes_risk_policy_metadata -v
```

Expected: FAIL with missing mapped keys.

- [ ] **Step 3: Update graph runtime safe updates and mapping**

In `_safe_graph_update()`, add these keys to `safe_keys`:

```python
        "risk_domain",
        "immediacy",
        "risk_confidence",
        "protective_signals",
        "risk_phase",
        "tool_gate_mode",
        "experience_validator_reasons",
```

In `_map_result()`, add these fields to `mapped`:

```python
            "risk_domain": result.get("risk_domain", ""),
            "immediacy": result.get("immediacy", ""),
            "risk_confidence": result.get("risk_confidence", ""),
            "protective_signals": result.get("protective_signals", []),
            "risk_phase": result.get("risk_phase", ""),
            "risk_response_policy": result.get("risk_response_policy", {}),
            "tool_gate_mode": result.get("tool_gate_mode", ""),
            "safety_context_pack": result.get("safety_context_pack", {}),
            "experience_validator_reasons": result.get("experience_validator_reasons", []),
```

- [ ] **Step 4: Persist metadata in chat service**

In `backend/app/services/chat_service.py`, add to `assistant_metadata`:

```python
        "risk_domain": assistant_result.get("risk_domain", ""),
        "immediacy": assistant_result.get("immediacy", ""),
        "risk_confidence": assistant_result.get("risk_confidence", ""),
        "protective_signals": assistant_result.get("protective_signals", []),
        "risk_phase": assistant_result.get("risk_phase", ""),
        "risk_response_policy": assistant_result.get("risk_response_policy", {}),
        "tool_gate_mode": assistant_result.get("tool_gate_mode", ""),
        "safety_context_summary": assistant_result.get("safety_context_pack", {}),
        "experience_validator_reasons": assistant_result.get("experience_validator_reasons", []),
```

In the stream response-validator event payload, add:

```python
            experience_validator_reasons=list(assistant_result.get("experience_validator_reasons", [])),
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```powershell
cd backend
python -m pytest tests/test_graph_runtime_streaming.py tests/test_chat_idempotency.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/graph_runtime.py backend/app/services/chat_service.py backend/tests/test_graph_runtime_streaming.py backend/tests/test_chat_idempotency.py
git commit -m "feat: persist risk policy metadata"
```

---

### Task 8: Full Backend Regression

**Files:**
- Test-only task; no source file edits unless a prior task exposed a real mismatch.

- [ ] **Step 1: Run focused safety and tooling suite**

Run:

```powershell
cd backend
python -m pytest ^
  tests/test_risk_policy.py ^
  tests/test_safety_context_service.py ^
  tests/test_safety_evaluation.py ^
  tests/test_conversation_control_rag.py ^
  tests/test_tooling.py ^
  tests/test_graph_runtime_streaming.py ^
  tests/test_chat_idempotency.py ^
  tests/test_voice_safety.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader backend smoke tests**

Run:

```powershell
cd backend
python -m pytest tests/test_chat_endpoints.py tests/test_response_node_streaming.py tests/test_response_memory_continuity.py tests/test_memory_service.py tests/test_user_context_pack_service.py -v
```

Expected: PASS.

- [ ] **Step 3: Inspect git status**

Run:

```powershell
git status --short
```

Expected: only intentional source/test changes are present. Existing unrelated untracked files such as `.playwright-mcp/*`, `backend/data/counseling_index_resume*.json`, `backend/test_stream.py`, and `ningyu-chat-lab-mobile.png` may still appear and should not be staged.

- [ ] **Step 4: Commit verification-only adjustments if needed**

If Step 1 or Step 2 forced small source/test fixes, commit them:

```powershell
git add backend/app backend/tests
git commit -m "test: cover backend risk control redesign"
```

Expected: a commit is created only if files changed during this verification task.

---

## Self-Review

Spec coverage:

- Risk classification fields are covered by Tasks 1 and 2.
- Safety context memory and high-risk continuity are covered by Task 3.
- Tool gate safety mode and safe web search are covered by Task 4.
- Policy-based crisis replies and dynamic length are covered by Task 5.
- Content and experience validator split is covered by Task 6.
- Audit and runtime metadata are covered by Task 7.
- Regression coverage is covered by Task 8.
- Knowledge-base work is intentionally excluded because the spec marks it out of scope.

Placeholder scan:

- This plan contains no placeholder markers, incomplete sections, or undefined task outputs.

Type consistency:

- Shared fields use the same names across tasks: `risk_domain`, `immediacy`, `risk_confidence`, `protective_signals`, `risk_phase`, `risk_response_policy`, `tool_gate_mode`, `safety_context_pack`, and `experience_validator_reasons`.
- `length_profile` and `char_budget` live inside `risk_response_policy` throughout the plan.
