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
EMBEDDING_INDEX_VERSION=rag-layered-v1
LOCAL_EMBEDDING_DEVICE=auto
LOCAL_EMBEDDING_BATCH_SIZE=8
LOCAL_EMBEDDING_MAX_LENGTH=1024
LOCAL_EMBEDDING_QUERY_MAX_LENGTH=512
LOCAL_EMBEDDING_DOCUMENT_MAX_LENGTH=2048
LOCAL_EMBEDDING_USE_FP16=auto
```

本地 embedding 依赖会下载较大的机器学习包，因此和基础后端依赖分开安装：

```bash
pip install -r requirements-local-embedding.txt
```

当前默认继续使用 `BAAI/bge-m3`。首次 embedding 请求会按需下载模型；CPU 可以运行但较慢，CUDA 可用时 `LOCAL_EMBEDDING_DEVICE=auto` 会优先使用 GPU 并自动启用 fp16。运行时 query embedding 使用 `LOCAL_EMBEDDING_QUERY_MAX_LENGTH`，语料重建/入库使用 `LOCAL_EMBEDDING_DOCUMENT_MAX_LENGTH`。修改 `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_DIM` 或 `EMBEDDING_INDEX_VERSION` 后，需要重建 Milvus 索引，避免不同向量空间混用。

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

## Terminal Chat

For local dialog testing without the frontend, run:

```bash
python scripts/terminal_chat.py
```

Useful commands:

- `/new [title]`
- `/threads`
- `/use <thread_id>`
- `/history [n]`
- `/exit`

For a one-shot smoke test:

```bash
python scripts/terminal_chat.py --message "我最近有点累"
```

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

## Milvus 索引

Milvus 是可重建索引。PostgreSQL 仍然是内容、来源、许可证和审核状态的真实来源。

To create collections and index published knowledge chunks:

```bash
python scripts/index_milvus.py --target knowledge
```

修改 `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_DIM`、`EMBEDDING_INDEX_VERSION`、chunking metadata 或 Milvus scalar fields 后，重建受影响的 Milvus collection：

```bash
python scripts/index_milvus.py --target all --recreate
python scripts/index_milvus.py --target counseling --recreate
```

CPU 上完整 BGE-M3 索引会比较慢。如果长任务中断，可以只补当前 `embedding_key` 下缺失的向量：

```bash
python scripts/index_milvus.py --target knowledge --missing-only
```

导入已审核的中文咨询对话语料时，系统会生成三层 RAG chunk：

- `turn_pair`：单个 user-assistant 轮次，主要用于语气、节奏和局部回应风格参考。
- `process_segment`：3-5 个轮次组成的咨询过程片段，默认 1 个 pair overlap，用于理解情绪变化和咨询师引导路径。
- `session_sketch`：脱敏后的整段咨询地图，只保留主题、情绪线索和干预路径，不保存逐字原文。

运行时默认检索 `1` 个 `process_segment` 和 `2` 个 `turn_pair`；续聊类 query 会允许 `1` 个 `session_sketch`、`1` 个 `process_segment` 和 `1` 个 `turn_pair`。prompt 中会优先展示 `display_text`，不会把较长的 `retrieval_text/content` 原样放进模型上下文。

导入并索引已审核的中文咨询对话语料：

```bash
python scripts/import_counseling_corpus.py --source smilechat --input-json data/smilechat.json --limit 20 --dry-run
python scripts/import_counseling_corpus.py --source smilechat --input-json data/smilechat.json --publish-reviewed
python scripts/import_counseling_corpus.py --source smilechat --input-dir data/counseling_corpus/smilechat/data --publish-reviewed
```

Supported counseling source keys are `soulchat_corpus`, `smilechat`, `cpsycound`, and `psydt_corpus`. PsyQA official full data and `efaqa-corpus-zh` are intentionally not default imports because they require separate authorization or usage checks.

如果 PostgreSQL 不可用，只需要把本地咨询语料写入 Milvus，可从 `backend/data/counseling_corpus` 直接索引：

```bash
python scripts/index_counseling_corpus_direct.py --source smilechat --limit 20
python scripts/index_counseling_corpus_direct.py --recreate
```

This direct path streams large JSON arrays instead of loading the full corpus into memory, cleans common PII patterns, filters high-risk or unsafe examples, and writes rows to the same `counseling_examples_v1` Milvus collection used by runtime retrieval.
