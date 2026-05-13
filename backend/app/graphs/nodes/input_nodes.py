from __future__ import annotations

from app.graphs.nodes.common import AgentState
from app.services.companion_style import normalize_custom_companion_style


async def normalize_input(state: AgentState) -> AgentState:
    normalized_text = (state.get("user_text") or state.get("voice_transcript") or "").strip()
    return {
        "normalized_text": normalized_text,
        "messages": state.get("recent_messages", []),
        "input_type": state.get("input_type", "text"),
        "audit_tags": ["input_normalized"],
    }


async def load_user_profile(state: AgentState) -> AgentState:
    existing_profile = state.get("profile", {})
    existing_preferences = state.get("companion_preferences", {})
    existing_profile_digest = state.get("user_profile_digest", {})
    existing_goal_state = state.get("goal_state", {})
    existing_context_pack = state.get("user_context_pack", {})
    existing_response_style = state.get("response_style", {})
    user_mode = state.get("user_mode") or existing_profile.get("user_mode", "adult")

    return {
        "profile": {
            "user_mode": user_mode,
            "nickname": existing_profile.get("nickname", "user"),
        },
        "companion_preferences": {
            "style": normalize_custom_companion_style(existing_preferences.get("style", "")),
            "question_tolerance": existing_preferences.get(
                "question_tolerance",
                "low" if user_mode == "teen" else "medium",
            ),
        },
        "user_profile_digest": existing_profile_digest if isinstance(existing_profile_digest, dict) else {},
        "goal_state": existing_goal_state if isinstance(existing_goal_state, dict) else {},
        "user_context_pack": existing_context_pack if isinstance(existing_context_pack, dict) else {},
        "memory_mode": state.get("memory_mode", "summary_only"),
        "response_style": {
            "short_sentences": existing_response_style.get("short_sentences", user_mode == "teen"),
            "tone": existing_response_style.get("tone", "supportive"),
        },
    }
