from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


DEFAULT_QUERY = "我最近很焦虑，晚上睡不着，总忍不住想工作上的事，怎么办？"


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


async def check_rag_ready(args: argparse.Namespace) -> int:
    from app.core.config import settings
    from app.services.counseling_vector_service import retrieve_counseling_examples_with_trace
    from app.services.embedding_service import embedding_client
    from app.services.milvus_service import milvus_store

    if not settings.counseling_rag_enabled:
        _print({"status": "error", "reason": "rag_disabled"})
        return 1
    if not settings.milvus_enabled:
        _print({"status": "error", "reason": "milvus_disabled"})
        return 1
    if not milvus_store.is_available:
        _print({"status": "error", "reason": "milvus_unavailable", "uri": milvus_store.uri})
        return 1

    vector = await embedding_client.embed_query(args.query)
    if vector is None:
        _print({"status": "error", "reason": "embedding_unavailable", "provider": embedding_client.provider})
        return 1

    state = {
        "normalized_text": args.query,
        "intent": "light_counseling",
        "risk_level": "L0",
        "control_category": "normal_support",
        "route_priority": "P2_support",
    }
    result = await retrieve_counseling_examples_with_trace(
        state,
        mode=args.mode,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
    )
    trace = result.trace
    if not result.examples:
        _print(
            {
                "status": "error",
                "reason": str(trace.get("skipped_reason") or trace.get("status") or "rag_empty"),
                "trace": trace,
            }
        )
        return 1

    _print(
        {
            "status": "rag_ready",
            "collection": milvus_store.counseling_collection,
            "embedding_provider": embedding_client.provider,
            "embedding_dim": len(vector),
            "hit_count": len(result.examples),
            "source_keys": [example.source_key for example in result.examples],
            "trace": trace,
        }
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Milvus, embedding, and counseling RAG readiness.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--mode", default="companion")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(check_rag_ready(args))
    except Exception as exc:  # noqa: BLE001 - startup diagnostics should return structured context.
        _print({"status": "error", "reason": "rag_ready_exception", "error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
