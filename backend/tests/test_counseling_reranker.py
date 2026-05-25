from __future__ import annotations

import unittest

from app.core.config import settings
from app.services.counseling_reranker import (
    RerankCandidate,
    RerankResult,
    fallback_select_candidates,
    model_reranker,
)


class CounselingModelRerankerTests(unittest.IsolatedAsyncioTestCase):
    def candidate(
        self,
        chunk_id: str,
        *,
        vector_score: float,
        chunk_type: str = "turn_pair",
        original_external_id: str | None = None,
    ) -> RerankCandidate:
        return RerankCandidate(
            chunk_id=chunk_id,
            text=f"用户：我很累\n咨询回应：{chunk_id}",
            distance=1.0 - vector_score,
            metadata={"display_text": f"display {chunk_id}", "source_key": "smilechat"},
            vector_score=vector_score,
            mode="soothe",
            chunk_type=chunk_type,
            original_external_id=original_external_id or chunk_id,
            source_key="smilechat",
        )

    def test_candidate_exposes_downstream_fields(self) -> None:
        candidate = self.candidate("turn", vector_score=0.82)

        self.assertEqual(candidate.text, "用户：我很累\n咨询回应：turn")
        self.assertAlmostEqual(candidate.distance, 0.18)
        self.assertEqual(candidate.metadata["display_text"], "display turn")

    def test_fallback_selects_process_and_turn_pairs_for_ordinary_queries(self) -> None:
        candidates = [
            self.candidate("process", vector_score=0.80, chunk_type="process_segment"),
            self.candidate("session", vector_score=0.79, chunk_type="session_sketch"),
            self.candidate("turn-1", vector_score=0.78, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.77, chunk_type="turn_pair"),
            self.candidate("turn-3", vector_score=0.76, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates("我最近压力很大", candidates, 4)

        self.assertEqual(
            [item.chunk_type for item in selected],
            ["process_segment", "turn_pair", "turn_pair", "turn_pair"],
        )

    def test_fallback_supports_legacy_keyword_call_shape(self) -> None:
        candidates = [
            self.candidate("process", vector_score=0.80, chunk_type="process_segment"),
            self.candidate("turn-1", vector_score=0.79, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.78, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates(candidates, query="我最近压力很大", limit=3)

        self.assertEqual([item.chunk_type for item in selected], ["process_segment", "turn_pair", "turn_pair"])

    def test_fallback_continuation_includes_session_sketch(self) -> None:
        candidates = [
            self.candidate("session", vector_score=0.70, chunk_type="session_sketch"),
            self.candidate("process", vector_score=0.69, chunk_type="process_segment"),
            self.candidate("turn", vector_score=0.68, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates("继续刚才的问题", candidates, 3)

        self.assertEqual([item.chunk_type for item in selected], ["session_sketch", "process_segment", "turn_pair"])

    def test_fallback_still_query_includes_session_sketch(self) -> None:
        candidates = [
            self.candidate("session", vector_score=0.70, chunk_type="session_sketch"),
            self.candidate("process", vector_score=0.69, chunk_type="process_segment"),
            self.candidate("turn", vector_score=0.68, chunk_type="turn_pair"),
        ]

        selected = fallback_select_candidates("还是这个问题", candidates, 3)

        self.assertEqual([item.chunk_type for item in selected], ["session_sketch", "process_segment", "turn_pair"])

    async def test_rerank_uses_worker_scores_when_available(self) -> None:
        original_score_pairs = model_reranker._score_pairs
        original_enabled = settings.counseling_rerank_enabled
        original_model = model_reranker.model

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            return [0.1, 0.9, 0.4]

        candidates = [
            self.candidate("a", vector_score=0.95),
            self.candidate("b", vector_score=0.70),
            self.candidate("c", vector_score=0.80),
        ]
        model_reranker._score_pairs = fake_score_pairs
        object.__setattr__(settings, "counseling_rerank_enabled", True)
        model_reranker.model = "test-reranker"
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=2,
                timeout_seconds=1.0,
            )
        finally:
            object.__setattr__(settings, "counseling_rerank_enabled", original_enabled)
            model_reranker.model = original_model
            model_reranker._score_pairs = original_score_pairs

        self.assertIsInstance(result, RerankResult)
        self.assertEqual(result.status, "hit")
        self.assertEqual([item.chunk_id for item in result.candidates], ["b", "c"])
        self.assertEqual(result.candidates[0].rerank_score, 0.9)
        self.assertIn("model_rerank", result.candidates[0].rerank_reasons)

    async def test_rerank_falls_back_when_worker_unavailable(self) -> None:
        original_score_pairs = model_reranker._score_pairs
        original_enabled = settings.counseling_rerank_enabled
        original_model = model_reranker.model

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            return None

        candidates = [
            self.candidate("process", vector_score=0.8, chunk_type="process_segment"),
            self.candidate("turn", vector_score=0.7, chunk_type="turn_pair"),
        ]
        model_reranker._score_pairs = fake_score_pairs
        object.__setattr__(settings, "counseling_rerank_enabled", True)
        model_reranker.model = "test-reranker"
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=2,
                timeout_seconds=1.0,
            )
        finally:
            object.__setattr__(settings, "counseling_rerank_enabled", original_enabled)
            model_reranker.model = original_model
            model_reranker._score_pairs = original_score_pairs

        self.assertEqual(result.status, "fallback")
        self.assertEqual([item.chunk_id for item in result.candidates], ["process", "turn"])
        self.assertEqual(result.reason, "reranker_unavailable")

    async def test_rerank_falls_back_when_disabled(self) -> None:
        original_score_pairs = model_reranker._score_pairs
        original_enabled = settings.counseling_rerank_enabled

        async def fail_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            raise AssertionError("disabled reranker must not call worker scoring")

        candidates = [
            self.candidate("process", vector_score=0.8, chunk_type="process_segment"),
            self.candidate("session", vector_score=0.7, chunk_type="session_sketch"),
            self.candidate("turn", vector_score=0.6, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.5, chunk_type="turn_pair"),
        ]
        model_reranker._score_pairs = fail_score_pairs
        object.__setattr__(settings, "counseling_rerank_enabled", False)
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=3,
                timeout_seconds=1.0,
            )
        finally:
            object.__setattr__(settings, "counseling_rerank_enabled", original_enabled)
            model_reranker._score_pairs = original_score_pairs

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "reranker_disabled")
        self.assertEqual([item.chunk_id for item in result.candidates], ["process", "turn", "turn-2"])

    async def test_rerank_falls_back_when_worker_raises(self) -> None:
        original_score_pairs = model_reranker._score_pairs
        original_enabled = settings.counseling_rerank_enabled
        original_model = model_reranker.model

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            raise TimeoutError("worker timed out")

        candidates = [
            self.candidate("process", vector_score=0.8, chunk_type="process_segment"),
            self.candidate("session", vector_score=0.7, chunk_type="session_sketch"),
            self.candidate("turn", vector_score=0.6, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.5, chunk_type="turn_pair"),
        ]
        model_reranker._score_pairs = fake_score_pairs
        object.__setattr__(settings, "counseling_rerank_enabled", True)
        model_reranker.model = "test-reranker"
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=3,
                timeout_seconds=1.0,
            )
        finally:
            object.__setattr__(settings, "counseling_rerank_enabled", original_enabled)
            model_reranker.model = original_model
            model_reranker._score_pairs = original_score_pairs

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "reranker_unavailable")
        self.assertEqual([item.chunk_id for item in result.candidates], ["process", "turn", "turn-2"])

    async def test_rerank_falls_back_when_worker_returns_non_finite_score(self) -> None:
        original_score_pairs = model_reranker._score_pairs
        original_enabled = settings.counseling_rerank_enabled
        original_model = model_reranker.model

        async def fake_score_pairs(query: str, documents: list[str], *, timeout_seconds: float) -> list[float] | None:
            return [float("nan"), 0.9, float("inf"), 0.2]

        candidates = [
            self.candidate("process", vector_score=0.8, chunk_type="process_segment"),
            self.candidate("session", vector_score=0.7, chunk_type="session_sketch"),
            self.candidate("turn", vector_score=0.6, chunk_type="turn_pair"),
            self.candidate("turn-2", vector_score=0.5, chunk_type="turn_pair"),
        ]
        model_reranker._score_pairs = fake_score_pairs
        object.__setattr__(settings, "counseling_rerank_enabled", True)
        model_reranker.model = "test-reranker"
        try:
            result = await model_reranker.rerank(
                query="我最近睡不好",
                candidates=candidates,
                limit=3,
                timeout_seconds=1.0,
            )
        finally:
            object.__setattr__(settings, "counseling_rerank_enabled", original_enabled)
            model_reranker.model = original_model
            model_reranker._score_pairs = original_score_pairs

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.reason, "reranker_unavailable")
        self.assertEqual([item.chunk_id for item in result.candidates], ["process", "turn", "turn-2"])


if __name__ == "__main__":
    unittest.main()
