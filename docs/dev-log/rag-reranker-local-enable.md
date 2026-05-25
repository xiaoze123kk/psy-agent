# RAG reranker local enablement

## 2026-05-21

### 背景/问题

面试模拟中需要立即开启咨询语料 RAG reranker，本地环境已开启 `COUNSELING_RAG_ENABLED` 和 `MILVUS_ENABLED`，但未开启 reranker。

### 关键改动

- 在 `backend/.env.local` 中开启 `COUNSELING_RERANK_ENABLED=1`。
- 使用默认 reranker 模型 `BAAI/bge-reranker-v2-m3`。
- 保留默认重排参数：`TOP_N=12`、`BATCH_SIZE=8`、`MAX_LENGTH=1024`、`TIMEOUT_SECONDS=20`。

### 验证结果

- 已在 `backend` 目录通过配置加载命令确认：`counseling_rerank_enabled=True`，模型为 `BAAI/bge-reranker-v2-m3`，`top_n=12`，`batch_size=8`，`max_length=1024`，`timeout=20.0`。
- 已通过 `app.services.local_reranker_worker` 完成一次本地模型加载和打分，返回 `{"ok": true}`。
- 已通过后端 `model_reranker.rerank` 封装完成一次重排 smoke check，结果为 `status=hit`、`reason=model_rerank`、`scored_count=2`，未触发 fallback。

### 后续事项

- 后端进程需要重启后才会读取新的 `.env.local` 配置。
- 如果本地模型依赖或缓存不可用，RAG 链路会按现有逻辑回退到确定性 chunk 配额选择。
