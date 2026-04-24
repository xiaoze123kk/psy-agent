# Backend

FastAPI + LangGraph backend scaffold for the counseling agent.

## Quick Start

1. Create and activate a virtual environment.
1. Install dependencies.

```bash
pip install -r requirements.txt
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
