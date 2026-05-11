# backend/AGENTS.md

后端是 FastAPI + LangGraph 服务，代码主要在 `app/`。

## 代码边界
- 路由在 `app/api/v1/endpoints/`。
- 图、状态和节点在 `app/graphs/`。
- 运行封装在 `app/services/graph_runtime.py`。
- 相关脚本在 `backend/scripts/`。

## 工作原则
- 改动尽量局部，优先沿用已有模式。
- API、图、服务层改动时，一并检查调用方和测试。
- PostgreSQL 是持久化真源，Milvus 只是可重建索引。

## 本地开发
- 环境变量通常放在 `backend/.env.local`。
- 安装基础依赖：`pip install -r requirements.txt`
- 安装测试依赖：`pip install -r requirements-dev.txt`
- 安装本地 embedding 依赖：`pip install -r requirements-local-embedding.txt`
- 启动服务：`uvicorn app.main:app --reload --port 8000`

## 验证
- 后端改动优先跑最小相关测试或 smoke check。
- 涉及 embedding 或 Milvus 时，按 `backend/README.md` 重新检查索引和配置。
- 如影响向量配置，优先跑 `python scripts/check_embedding.py`。
