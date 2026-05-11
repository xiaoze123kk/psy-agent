from typing import Literal

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    thread_id: str
    session_id: str
    thread_mode: Literal["companion", "knowledge", "test", "crisis"]
    user_mode: Literal["teen", "adult"]
    locale: str

    input_type: Literal["text", "voice", "test_result", "system"]
    user_text: str
    normalized_text: str
    voice_transcript: str

    messages: list[dict]
    recent_messages: list[dict]
    last_summary: str

    profile: dict
    companion_preferences: dict
    memory_mode: Literal["off", "summary_only", "long_term"]

    memory_index: list[dict]
    retrieved_memories: list[dict]

    intent: Literal[
        "vent",
        "soothe",
        "light_counseling",
        "daily_checkin",
        "crisis",
        "other",
    ]
    risk_level: Literal["L0", "L1", "L2", "L3"]
    risk_reasons: list[str]
    semantic_risk: dict
    risk_source: str
    risk_reason_codes: list[str]
    requires_safety_check: bool

    route_priority: Literal[
        "P0_immediate_safety",
        "P1_red_flag",
        "P2_support",
        "P3_bridge_boundary",
        "P4_system_protection",
    ]
    control_category: str
    control_reasons: list[str]
    control_confidence: float
    risk_formulation: dict
    response_contract: dict
    memory_policy: Literal["write_safe_summary", "skip_sensitive", "crisis_audit_only"]
    rag_policy: dict
    rag_used: bool
    rag_skipped_reason: str
    retrieved_counseling_examples: list[dict]
    validator_blocked: bool
    validator_reasons: list[str]
    delivery_status: Literal["generated", "failed_no_reply", "safety_fallback"]
    failure_reason: str | None
    retryable: bool

    response_style: dict
    system_policy: dict

    assistant_text: str
    suggested_actions: list[str]

    session_summary: str
    memory_candidates: list[dict]
    memory_write_decisions: list[dict]
    memory_policy_reason: str
    should_write_memory: bool
    audit_tags: list[str]
