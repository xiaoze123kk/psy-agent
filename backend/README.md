# Backend

FastAPI + LangGraph backend scaffold for the counseling agent.

## Quick Start

1. Create and activate a virtual environment.
1. Install dependencies.

```bash
pip install -r requirements.txt
```

For local test runs, install the dev dependency set:

```bash
pip install -r requirements-dev.txt
```

1. Configure local PostgreSQL in `backend/.env.local`.

```bash
DATABASE_URL=postgresql+psycopg://postgres:123456@127.0.0.1:5432/psychology_agent
```

1. Create the local database once.

```bash
createdb -h 127.0.0.1 -p 5432 -U postgres psychology_agent
```

1. Initialize database schema with the SQL migration script.

```bash
# run in project root
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0001_init.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0002_refresh_tokens.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0003_username_auth.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0004_knowledge.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0005_knowledge_beta.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0006_privacy.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0007_counseling_corpus_milvus.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0008_app_runtime_schema_alignment.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0009_memory_system.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0010_chat_turn_idempotency.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0011_conversation_turn_traces.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0012_pending_memory_jobs.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f database/migrations/0013_companion_styles.sql
```

Milvus vector search is optional. For local standalone Milvus:

```bash
# run in project root
docker compose -f docker-compose.milvus.yml up -d
```

Then enable vector retrieval in `backend/.env.local`:

```bash
MILVUS_ENABLED=1
MILVUS_URI=http://localhost:19530
MILVUS_DB_NAME=default
MILVUS_COLLECTION_PREFIX=psych_agent

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
LOCAL_EMBEDDING_DEVICE=auto
LOCAL_EMBEDDING_BATCH_SIZE=8
LOCAL_EMBEDDING_MAX_LENGTH=1024
LOCAL_EMBEDDING_USE_FP16=auto
```

Local embedding dependencies are kept separate from the base backend install because they download larger ML packages:

```bash
pip install -r requirements-local-embedding.txt
```

`BAAI/bge-m3` is downloaded lazily on the first embedding request. CPU works but is slower; with CUDA available, `LOCAL_EMBEDDING_DEVICE=auto` uses GPU and enables fp16 automatically. To use DashScope instead, set `EMBEDDING_PROVIDER=dashscope`, `EMBEDDING_MODEL=text-embedding-v4`, and `DASHSCOPE_API_KEY`, then recreate the Milvus index so vectors are not mixed across embedding models.

To smoke test the configured embedding provider:

```bash
python scripts/check_embedding.py
```

1. Run the API.

```bash
uvicorn app.main:app --reload --port 8000
```

## API Base

- Health: `GET /health`
- API v1 root: `GET /api/v1`

## Structure

- `app/api/v1/endpoints`: API route skeletons
- `app/graphs`: LangGraph state, routing, nodes, and main graph
- `app/services/graph_runtime.py`: Graph execution wrapper

## Knowledge Import

Knowledge Beta supports two offline import paths. Both keep new external content as `draft` until a reviewer publishes it.

To fetch one whitelisted open-source page and create a review draft:

```bash
python scripts/import_knowledge_sources.py --source nimh_public_domain --fetch-url https://www.nimh.nih.gov/health/publications/panic-disorder-when-fear-overwhelms --slug nimh-panic-disorder --category anxiety --tags anxiety,panic --output-json data/nimh-panic-draft.json
python scripts/import_knowledge_sources.py --source nimh_public_domain --fetch-url https://www.nimh.nih.gov/health/publications/panic-disorder-when-fear-overwhelms --slug nimh-panic-disorder --category anxiety --tags anxiety,panic --rewrite-with-llm
```

To batch import high-confidence public-domain sources directly as published records:

```bash
python scripts/import_knowledge_sources.py --source medlineplus_public_domain --batch-medlineplus-mental-health --include-substance --include-adjacent --publish-reviewed
python scripts/import_knowledge_sources.py --source medlineplus_public_domain --batch-medlineplus-high-confidence --limit 100 --publish-reviewed
python scripts/import_knowledge_sources.py --source nimh_public_domain --batch-nimh-publications --publish-reviewed
python scripts/import_knowledge_sources.py --source nimh_public_domain --batch-nimh-topics --publish-reviewed
```

To import reviewed JSON drafts, prepare a JSON list with `slug`, `title`, `category`, `audience`, `summary_30s`, `explanation_3min`, `tags`, `source_url`, `actions`, and `seek_help_when`, then run:

```bash
python scripts/import_knowledge_sources.py --source nimh_public_domain --input-json data/knowledge_drafts.json --dry-run
python scripts/import_knowledge_sources.py --source nimh_public_domain --input-json data/knowledge_drafts.json --publish-reviewed
```

Supported source keys are `nimh_public_domain`, `medlineplus_public_domain`, `childmind_mhdb`, and `internal_curated`.

## Milvus Indexing

Milvus is a rebuildable index. PostgreSQL remains the source of truth for content, source, license, and review state.

To create collections and index published knowledge chunks:

```bash
python scripts/index_milvus.py --target knowledge
```

After changing `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, or `EMBEDDING_DIM`, rebuild the affected Milvus collections:

```bash
python scripts/index_milvus.py --target all --recreate
```

On CPU, full BGE-M3 indexing can be slow. If a long run is interrupted, resume only missing vectors:

```bash
python scripts/index_milvus.py --target knowledge --missing-only
```

To import reviewed Chinese counseling dialogue corpora and index them as style examples:

```bash
python scripts/import_counseling_corpus.py --source smilechat --input-json data/smilechat.json --limit 20 --dry-run
python scripts/import_counseling_corpus.py --source smilechat --input-json data/smilechat.json --publish-reviewed
```

Supported counseling source keys are `soulchat_corpus`, `smilechat`, `cpsycound`, and `psydt_corpus`. PsyQA official full data and `efaqa-corpus-zh` are intentionally not default imports because they require separate authorization or usage checks.

If PostgreSQL is unavailable and you only need the local counseling corpora in Milvus for retrieval-augmented counselor style examples, index directly from `backend/data/counseling_corpus`:

```bash
python scripts/index_counseling_corpus_direct.py --source smilechat --limit 20
python scripts/index_counseling_corpus_direct.py --recreate
```

This direct path streams large JSON arrays instead of loading the full corpus into memory, cleans common PII patterns, filters high-risk or unsafe examples, and writes rows to the same `counseling_examples_v1` Milvus collection used by runtime retrieval.
