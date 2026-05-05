from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, init_db
from app.services.milvus_service import milvus_store
from app.services.vector_index_service import index_counseling_chunks, index_knowledge_chunks


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create Milvus collections and rebuild vector indexes.")
    parser.add_argument("--target", choices=["all", "knowledge", "counseling"], default="all")
    parser.add_argument("--source-key", help="Only index one counseling corpus source.")
    parser.add_argument("--limit", type=int, help="Limit rows for smoke tests.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate target Milvus collections before indexing.")
    parser.add_argument("--missing-only", action="store_true", help="Only index rows missing from the current embedding_key.")
    args = parser.parse_args()

    init_db()
    drop_results = milvus_store.drop_collections(args.target) if args.recreate else None
    if args.target == "knowledge":
        milvus_ready = milvus_store.ensure_knowledge_collection()
    elif args.target == "counseling":
        milvus_ready = milvus_store.ensure_counseling_collection()
    else:
        milvus_ready = milvus_store.ensure_collections()
    results: dict[str, object] = {"milvus_ready": milvus_ready}
    if drop_results is not None:
        results["dropped"] = drop_results
    with SessionLocal() as db:
        if args.target in {"all", "knowledge"}:
            counts = await index_knowledge_chunks(db, limit=args.limit, missing_only=args.missing_only)
            results["knowledge"] = {"indexed": counts.indexed, "skipped": counts.skipped}
        if args.target in {"all", "counseling"}:
            counts = await index_counseling_chunks(
                db,
                source_key=args.source_key,
                limit=args.limit,
                missing_only=args.missing_only,
            )
            results["counseling"] = {"indexed": counts.indexed, "skipped": counts.skipped}

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
