from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import math
import os
import sys
from time import perf_counter
from typing import Any

from app.core.config import BASE_DIR, settings


logger = logging.getLogger(__name__)

CONTINUATION_PATTERNS = ("继续", "还是", "刚才", "上次", "前面", "那个问题", "接着")
FALLBACK_REASON = "fallback_quota"


@dataclass(init=False)
class RerankCandidate:
    chunk_id: str
    text: str
    distance: float
    metadata: dict[str, Any]
    vector_score: float
    mode: str
    chunk_type: str
    original_external_id: str
    source_key: str
    content: str
    display_text: str
    rerank_score: float | None = None
    rerank_reasons: list[str] | None = None

    def __init__(
        self,
        *,
        chunk_id: str,
        vector_score: float,
        mode: str,
        chunk_type: str,
        original_external_id: str,
        source_key: str,
        text: str | None = None,
        distance: float | None = None,
        metadata: dict[str, Any] | None = None,
        content: str | None = None,
        display_text: str | None = None,
        rerank_score: float | None = None,
        rerank_reasons: list[str] | None = None,
    ) -> None:
        resolved_text = str(text or display_text or content or "")
        resolved_metadata = dict(metadata or {})
        resolved_content = str(content or resolved_text)
        resolved_display_text = str(display_text or resolved_metadata.get("display_text") or resolved_text)

        self.chunk_id = chunk_id
        self.text = resolved_text
        self.distance = float(distance if distance is not None else 1.0 - vector_score)
        self.metadata = resolved_metadata
        self.vector_score = float(vector_score)
        self.mode = mode
        self.chunk_type = chunk_type
        self.original_external_id = original_external_id
        self.source_key = source_key
        self.content = resolved_content
        self.display_text = resolved_display_text
        self.rerank_score = rerank_score
        self.rerank_reasons = list(rerank_reasons or [])


@dataclass
class RerankResult:
    candidates: list[RerankCandidate]
    status: str
    reason: str
    duration_ms: int
    scored_count: int


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _safe_limit(limit: int) -> int:
    return max(int(limit), 0)


def _quota_for_query(query: str, limit: int) -> dict[str, int]:
    if any(pattern in query for pattern in CONTINUATION_PATTERNS):
        return {"session_sketch": 1, "process_segment": 1, "turn_pair": max(limit - 2, 0)}
    return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}


def _with_reason(candidate: RerankCandidate, *, score: float, reason: str) -> RerankCandidate:
    reasons = list(candidate.rerank_reasons or [])
    if reason not in reasons:
        reasons.append(reason)
    return RerankCandidate(
        chunk_id=candidate.chunk_id,
        text=candidate.text,
        distance=candidate.distance,
        metadata=candidate.metadata,
        vector_score=candidate.vector_score,
        mode=candidate.mode,
        chunk_type=candidate.chunk_type,
        original_external_id=candidate.original_external_id,
        source_key=candidate.source_key,
        content=candidate.content,
        display_text=candidate.display_text,
        rerank_score=float(score),
        rerank_reasons=reasons,
    )


def _can_take(candidate: RerankCandidate, used_sources: dict[str, int]) -> bool:
    source = candidate.original_external_id or candidate.chunk_id
    return used_sources.get(source, 0) < 2


def _record_source(candidate: RerankCandidate, used_sources: dict[str, int]) -> None:
    source = candidate.original_external_id or candidate.chunk_id
    used_sources[source] = used_sources.get(source, 0) + 1


def fallback_select_candidates(
    query_or_candidates: str | list[RerankCandidate],
    candidates: list[RerankCandidate] | None = None,
    limit: int | None = None,
    *,
    query: str | None = None,
    reason: str = FALLBACK_REASON,
) -> list[RerankCandidate]:
    if isinstance(query_or_candidates, str):
        resolved_query = query_or_candidates
        resolved_candidates = candidates or []
    else:
        resolved_query = query or ""
        resolved_candidates = query_or_candidates
    safe_limit = _safe_limit(limit or 0)
    if safe_limit <= 0:
        return []

    quota = _quota_for_query(resolved_query, safe_limit)
    selected: list[RerankCandidate] = []
    selected_ids: set[str] = set()
    used_sources: dict[str, int] = {}

    for desired_type, desired_count in quota.items():
        if desired_count <= 0:
            continue
        used_for_type = 0
        for candidate in resolved_candidates:
            if candidate.chunk_id in selected_ids:
                continue
            if candidate.chunk_type != desired_type:
                continue
            if not _can_take(candidate, used_sources):
                continue
            selected.append(_with_reason(candidate, score=candidate.vector_score, reason=reason))
            selected_ids.add(candidate.chunk_id)
            _record_source(candidate, used_sources)
            used_for_type += 1
            if len(selected) >= safe_limit or used_for_type >= desired_count:
                break

    for candidate in resolved_candidates:
        if len(selected) >= safe_limit:
            break
        if candidate.chunk_id in selected_ids:
            continue
        if not _can_take(candidate, used_sources):
            continue
        selected.append(_with_reason(candidate, score=candidate.vector_score, reason=reason))
        selected_ids.add(candidate.chunk_id)
        _record_source(candidate, used_sources)

    return selected


class CounselingModelReranker:
    def __init__(self) -> None:
        self.model = settings.counseling_rerank_model.strip()
        self.batch_size = max(settings.counseling_rerank_batch_size, 1)
        self.max_length = max(settings.counseling_rerank_max_length, 1)
        self.timeout_seconds = max(settings.counseling_rerank_timeout_seconds, 0.001)
        self._worker_process: Any | None = None
        self._worker_lock: asyncio.Lock | None = None

    @property
    def is_enabled(self) -> bool:
        return bool(settings.counseling_rerank_enabled and self.model)

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[RerankCandidate],
        limit: int,
        timeout_seconds: float | None = None,
    ) -> RerankResult:
        started_at = perf_counter()
        safe_limit = _safe_limit(limit)
        if safe_limit <= 0 or not candidates:
            return RerankResult([], "empty", "no_candidates", _elapsed_ms(started_at), 0)

        if not self.is_enabled:
            return self._fallback_result(
                query=query,
                candidates=candidates,
                limit=safe_limit,
                reason="reranker_disabled",
                started_at=started_at,
            )

        timeout = max(float(timeout_seconds or self.timeout_seconds), 0.001)
        try:
            scores = await self._score_pairs(
                query,
                [candidate.text for candidate in candidates],
                timeout_seconds=timeout,
            )
        except Exception as exc:
            logger.warning("Counseling reranker scoring failed: %s", exc)
            scores = None

        if scores is None or len(scores) != len(candidates):
            return self._fallback_result(
                query=query,
                candidates=candidates,
                limit=safe_limit,
                reason="reranker_unavailable",
                started_at=started_at,
            )
        scores = self._coerce_scores(scores, expected_count=len(candidates))
        if scores is None:
            return self._fallback_result(
                query=query,
                candidates=candidates,
                limit=safe_limit,
                reason="reranker_unavailable",
                started_at=started_at,
            )

        try:
            scored_candidates = [
                _with_reason(candidate, score=score, reason="model_rerank")
                for candidate, score in zip(candidates, scores, strict=True)
            ]
            scored_candidates.sort(key=lambda item: (item.rerank_score or 0.0, item.vector_score), reverse=True)

            selected: list[RerankCandidate] = []
            used_sources: dict[str, int] = {}
            for candidate in scored_candidates:
                if not _can_take(candidate, used_sources):
                    continue
                selected.append(candidate)
                _record_source(candidate, used_sources)
                if len(selected) >= safe_limit:
                    break
        except Exception as exc:
            logger.warning("Counseling reranker result processing failed: %s", exc)
            return self._fallback_result(
                query=query,
                candidates=candidates,
                limit=safe_limit,
                reason="reranker_unavailable",
                started_at=started_at,
            )

        return RerankResult(
            candidates=selected,
            status="hit",
            reason="model_rerank",
            duration_ms=_elapsed_ms(started_at),
            scored_count=len(scores),
        )

    def _fallback_result(
        self,
        *,
        query: str,
        candidates: list[RerankCandidate],
        limit: int,
        reason: str,
        started_at: float,
    ) -> RerankResult:
        return RerankResult(
            candidates=fallback_select_candidates(query, candidates, limit, reason=reason),
            status="fallback",
            reason=reason,
            duration_ms=_elapsed_ms(started_at),
            scored_count=0,
        )

    async def _score_pairs(
        self,
        query: str,
        documents: list[str],
        *,
        timeout_seconds: float,
    ) -> list[float] | None:
        if not self.is_enabled or not query.strip() or not documents:
            return None

        lock = self._get_worker_lock()
        async with lock:
            process = await self._ensure_worker()
            if process is None or process.stdin is None or process.stdout is None:
                return None

            payload = json.dumps(
                {"query": query, "documents": documents},
                ensure_ascii=True,
            ).encode("ascii") + b"\n"
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout_seconds)
            except (BrokenPipeError, ConnectionError, asyncio.TimeoutError) as exc:
                logger.warning("Local reranker worker request failed: %s", exc)
                await self._stop_worker()
                return None

            if not line:
                logger.warning("Local reranker worker exited before returning scores.")
                await self._stop_worker()
                return None

            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning("Local reranker worker returned invalid JSON: %s", exc)
                await self._stop_worker()
                return None

            if not isinstance(response, dict) or not response.get("ok"):
                logger.warning("Local reranker worker failed: %s", response)
                await self._stop_worker()
                return None

            return self._coerce_scores(response.get("scores"), expected_count=len(documents))

    async def aclose(self) -> None:
        await self._stop_worker()

    def _get_worker_lock(self) -> asyncio.Lock:
        if self._worker_lock is None:
            self._worker_lock = asyncio.Lock()
        return self._worker_lock

    async def _ensure_worker(self) -> Any | None:
        if self._worker_process is not None and self._worker_process.returncode is None:
            return self._worker_process

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["LOCAL_RERANKER_WORKER_MODE"] = "1"
        try:
            self._worker_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.services.local_reranker_worker",
                cwd=str(BASE_DIR),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1024 * 1024,
            )
        except Exception as exc:  # pragma: no cover - process startup depends on host runtime
            logger.warning("Local reranker worker start failed: %s", exc)
            self._worker_process = None
        return self._worker_process

    async def _stop_worker(self) -> None:
        process = self._worker_process
        self._worker_process = None
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3)
        except Exception:  # pragma: no cover - defensive cleanup
            try:
                process.kill()
            except Exception:
                pass

    def _coerce_scores(self, raw_scores: Any, *, expected_count: int) -> list[float] | None:
        if hasattr(raw_scores, "tolist"):
            raw_scores = raw_scores.tolist()
        if not isinstance(raw_scores, list) or len(raw_scores) != expected_count:
            logger.warning("Reranker score count mismatch: expected %s, got %s", expected_count, len(raw_scores or []))
            return None
        try:
            scores = [float(score) for score in raw_scores]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(score) for score in scores):
            logger.warning("Reranker returned non-finite score.")
            return None
        return scores


model_reranker = CounselingModelReranker()
