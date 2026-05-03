# Backend

FastAPI + LangGraph backend scaffold for the counseling agent.

## Quick Start

1. Create and activate a virtual environment.
1. Install dependencies.

```bash
pip install -r requirements.txt
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
