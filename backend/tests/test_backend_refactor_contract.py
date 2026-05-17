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
