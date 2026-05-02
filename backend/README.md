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
