from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.embedding_service import embedding_client


async def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the configured embedding provider.")
    parser.add_argument(
        "--text",
        action="append",
        help="Text to embed. Can be passed multiple times.",
    )
    args = parser.parse_args()

    texts = args.text or [
        "最近总是焦虑，晚上睡不着。",
        "我在人际关系里总担心被抛下。",
    ]
    vectors = await embedding_client.embed_texts(texts)
    if vectors is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "provider": embedding_client.provider,
                    "model": embedding_client.model,
                    "embedding_key": embedding_client.embedding_key,
                    "index_version": embedding_client.index_version,
                    "device": embedding_client.resolved_local_device,
                    "batch_size": embedding_client.local_batch_size,
                    "query_max_length": embedding_client.local_query_max_length,
                    "document_max_length": embedding_client.local_document_max_length,
                    "reason": "embedding provider returned no vectors",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    dims = [len(vector) for vector in vectors]
    norms = [round(math.sqrt(sum(value * value for value in vector)), 6) for vector in vectors]
    print(
        json.dumps(
            {
                "ok": True,
                "provider": embedding_client.provider,
                "model": embedding_client.model,
                "embedding_key": embedding_client.embedding_key,
                "index_version": embedding_client.index_version,
                "device": embedding_client.resolved_local_device,
                "batch_size": embedding_client.local_batch_size,
                "query_max_length": embedding_client.local_query_max_length,
                "document_max_length": embedding_client.local_document_max_length,
                "count": len(vectors),
                "dims": dims,
                "norms": norms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
