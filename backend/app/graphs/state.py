from typing import Literal

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    thread_id: str
    session_id: str
    user_mode: Literal["teen", "adult"]
    locale: str

    input_type: Literal["text", "voice", "test_result", "system"]
    user_text: str
    normalized_text: str
    voice_transcript: str

    messages: list[dict]
    recent_messages: list[dict]

    profile: dict
    companion_preferences: dict
    memory_mode: Literal["off", "summary_only", "long_term"]

    retrieved_memories: list[dict]
    retrieved_knowledge: list[dict]
    retrieved_test_context: dict
    retrieved_character_context: list[dict]

    intent: Literal[
        "vent",
        "soothe",
        "light_counseling",
        "knowledge_qa",
        "test_interpretation",
        "anime_match",
        "daily_checkin",
        "crisis",
        "other",
    ]
    risk_level: Literal["L0", "L1", "L2", "L3"]
    risk_reasons: list[str]

    response_style: dict
    system_policy: dict

    assistant_text: str
    suggested_actions: list[str]

    session_summary: str
    memory_candidates: list[dict]
    should_write_memory: bool
    audit_tags: list[str]
