# TTFT RAG Rerank Latency Design

## 背景

本地前后端启动后，用户反馈首次 TTFT 很长。当前聊天流已经能很快建立 SSE 连接并返回进度事件，但首个助手文本 token 必须等 LangGraph 中的 `example_retriever` 节点完成后才会出现。近期真实 trace 和一次本地诊断请求都显示，等待主要发生在咨询 RAG 检索和本地 reranker 阶段。

最近真实对话 trace：

- `example_retriever`: 26202ms
- `embedding_duration_ms`: 8661ms
- `milvus_duration_ms`: 508ms
- `rerank_duration_ms`: 17020ms
- `companion_response`: 3134ms

后端进程 warm 后的诊断请求：

- SSE 首个 `graph_update`: 约 40ms 到 50ms
- 首个文本 `token`: 约 20309ms
- `embedding_duration_ms`: 约 205ms 到 241ms
- `rerank_duration_ms`: 约 15841ms 到 16397ms

结论是：首次请求有 embedding worker 冷启动问题，但 warm 后 TTFT 仍高，主要原因是 CPU 本地 reranker 对 40 条候选进行同步前置重排。`start-local.ps1` 的 RAG readiness check 运行在独立 Python 进程中，不能代表正在监听 8000 的后端进程已经 warm。

## 目标

- 将本地后端刚启动后的首轮 TTFT 降到可接受范围，目标小于 8 秒。
- 将 warm 后常态低风险聊天 TTFT 降到可接受范围，目标小于 5 秒。
- 保留咨询 RAG 能力，不默认关闭 RAG。
- reranker 慢或冷启动时降级为确定性向量召回选择，而不是阻塞首 token 十几秒。
- 保持现有 trace 可解释，并补充能判断“候选数、模型重排数、超时预算、warmup 状态”的字段。

## 非目标

- 不重构 LangGraph 为“先生成、后补 RAG”的新流式架构。
- 不在本轮引入新的向量数据库、缓存服务或外部 rerank API。
- 不默认关闭 `COUNSELING_RAG_ENABLED`。
- 不改变危机、安全和高风险场景下的现有 RAG 禁用策略。
- 不把 `app.db.models.utcnow()` 全局迁移为 timezone-aware UTC。

## 推荐方案

采用“进程内预热 + rerank 实时预算 + 候选数裁剪 + fallback”的方案。

这个方案比直接关闭 reranker 更稳，因为它保留了高质量重排能力；也比“先答后检索”改动更小，因为当前阻塞点可以在现有 RAG 服务边界内解决。

## 方案对比

### 方案 A：预热 + 限制 rerank 实时成本 + fallback

后端启动时预热真实 API 进程中的 embedding worker 和 reranker worker。实时请求中只把向量召回前 N 条送进模型 reranker，并给 reranker 设置硬超时。超时后退回现有 `fallback_select_candidates()`。

优点：

- 改动集中在启动、RAG 服务和 reranker 服务。
- 保留 RAG 命中和 reranker 质量。
- 超时时仍能继续生成，不产生 `stream_failed`。
- trace 可以明确解释是否走了 fallback。

缺点：

- CPU reranker 仍会消耗资源，只是被预算限制。
- fallback 的示例排序质量低于完整模型重排。

### 方案 B：本地默认关闭 reranker

本地开发环境将 `COUNSELING_RERANK_ENABLED=0`，只使用向量召回和确定性配额选择。

优点：

- TTFT 下降最明显。
- 实现最简单。

缺点：

- RAG 示例质量下降。
- 容易掩盖生产或高质量环境中 reranker 的真实问题。
- 已经启用 reranker 的现有 dev-log 和配置会被语义反转。

### 方案 C：先生成，后补 RAG

把 RAG 从首 token 前置链路中拆出，让助手先基于记忆和上下文生成，再将 RAG 作为后续补充或下一轮上下文。

优点：

- 用户感知 TTFT 最好。
- RAG 慢时对首 token 没有直接影响。

缺点：

- 需要重构 graph 节点顺序、prompt 构造和流式事件语义。
- 需要重新定义 RAG 对当轮回复的作用，风险较高。
- 不适合作为当前问题的第一步修复。

## 设计细节

### 1. 后端真实进程内预热

修改 `backend/app/main.py`，保留现有 embedding warmup，并新增 reranker warmup。

启动条件：

- `settings.counseling_rag_enabled` 为 true。
- `settings.milvus_enabled` 为 true。
- `settings.embedding_provider` 为 `local` 时，按 `LOCAL_EMBEDDING_WARM_ON_STARTUP` 控制 embedding warmup。
- `COUNSELING_RERANK_WARM_ON_STARTUP` 为 true 且 `COUNSELING_RERANK_ENABLED` 为 true 时，执行 reranker warmup。

新增设置项：

- `counseling_rerank_warm_on_startup: bool`

新增环境变量：

- `COUNSELING_RERANK_WARM_ON_STARTUP=1`

reranker warmup 行为：

- 调用 `model_reranker.rerank()`。
- query 使用短文本，例如 `我今天有点累`。
- candidates 使用 1 到 2 个短文本 `RerankCandidate`。
- limit 为 1。
- timeout 使用 `min(settings.counseling_rerank_timeout_seconds, 10)`。
- 只记录日志，不阻塞 FastAPI 完成 startup。

失败处理：

- warmup 异常只记录 warning。
- shutdown 时调用 `model_reranker.aclose()`，避免后台 worker 泄漏。

### 2. 启动脚本默认设置低延迟环境

修改 `scripts/start-backend.ps1`。

当外部进程环境没有显式设置时，脚本默认注入：

- `LOCAL_EMBEDDING_USE_WORKER=1`
- `LOCAL_EMBEDDING_WARM_ON_STARTUP=1`
- `COUNSELING_RERANK_WARM_ON_STARTUP=1`
- `EMBEDDING_TIMEOUT_SECONDS=120`
- `RAG_RETRIEVAL_TIMEOUT_SECONDS=120`
- `COUNSELING_RERANK_TIMEOUT_SECONDS=5`

这里的默认值只影响脚本启动的本地后端进程，不写入 `.env.local`，不覆盖用户显式环境变量。

### 3. 限制模型 rerank 候选数

当前 `backend/app/services/counseling_vector_service.py` 会把 Milvus 召回的全部 candidates 传给 `model_reranker.rerank()`。当 `COUNSELING_RECALL_TOP_N=40` 时，CPU reranker 每轮处理 40 条，导致常态 TTFT 高。

修改为：

- Milvus 仍按 `COUNSELING_RECALL_TOP_N` 召回，保证覆盖面。
- 构造 candidates 后，按向量分保留模型重排候选前 N 条。
- N 默认使用 `COUNSELING_RERANK_TOP_N`。
- 若 `COUNSELING_RERANK_TOP_N <= 0`，不进入模型 rerank，直接 fallback 选择。
- 最终对话引用示例仍最多 `safe_limit` 条，当前为 3 条。

trace 新增：

- `rerank_candidate_count`: Milvus 去重、安全过滤后的候选总数。
- `rerank_model_candidate_count`: 实际送入模型 reranker 的候选数。

### 4. 修正 rerank timeout 语义

当前调用传入 `remaining_seconds()`，导致 `COUNSELING_RERANK_TIMEOUT_SECONDS=20` 不是真实硬上限。修改为：

```python
rerank_timeout = min(
    remaining_seconds(),
    max(settings.counseling_rerank_timeout_seconds, 0.001),
)
```

同时把 timeout 传给 `model_reranker.rerank()`。

trace 新增：

- `rerank_timeout_ms`

### 5. timeout fallback 可解释化

当前 `CounselingModelReranker._score_pairs()` 超时时返回 `None`，外层会得到 `reason="reranker_unavailable"`，不能区分 worker 崩溃、模型错误和超时。

修改方式：

- 新增私有 dataclass，例如 `_ScorePairsResult`，字段为 `scores: list[float] | None` 和 `failure_reason: str | None`。
- `_score_pairs()` 返回 `_ScorePairsResult`，不再只返回 `list[float] | None`。
- 捕获 `asyncio.TimeoutError` 时返回 `scores=None, failure_reason="reranker_timeout"`。
- worker 请求失败、进程退出、非法 JSON 或响应失败时返回 `scores=None, failure_reason="reranker_unavailable"`。
- `rerank()` 收到无 scores 时调用 `_fallback_result()`，reason 使用 `_ScorePairsResult.failure_reason or "reranker_unavailable"`。
- disabled 仍使用 `reranker_disabled`。

这样 timeout、worker 不可用和主动关闭 reranker 会在 trace 中形成不同原因，便于判断 TTFT 优化是否生效。

### 6. 前端感知不作为本轮主修

前端已经能收到早期 `graph_update`，问题不是连接建立慢。本轮不改前端 UI，只要求后端 trace 保留可解释字段，便于现有 trace 面板展示或后续接入。

## 数据流

请求进入 `/api/v1/chat/threads/{thread_id}/stream` 后：

1. `process_message_turn_stream()` 准备 turn 和上下文。
2. LangGraph 进入 `example_retriever`。
3. `retrieve_counseling_examples_with_trace()` 生成 query embedding。
4. Milvus 按 `COUNSELING_RECALL_TOP_N` 召回候选。
5. 服务层过滤 unsafe 和重复候选。
6. 仅前 `COUNSELING_RERANK_TOP_N` 条进入模型 reranker。
7. reranker 在 `COUNSELING_RERANK_TIMEOUT_SECONDS` 上限内返回。
8. 若超时或不可用，fallback 选择候选。
9. `example_retriever` 结束，进入 response 节点。
10. 首个助手文本 token 开始流出。

## 配置默认值

本轮推荐本地脚本默认值：

```text
LOCAL_EMBEDDING_USE_WORKER=1
LOCAL_EMBEDDING_WARM_ON_STARTUP=1
COUNSELING_RERANK_WARM_ON_STARTUP=1
COUNSELING_RERANK_TIMEOUT_SECONDS=5
COUNSELING_RERANK_TOP_N=12
COUNSELING_RECALL_TOP_N=40
```

保持 `.env.local` 不自动改写。用户显式设置的环境变量优先级最高。

## 错误处理

- embedding warmup 失败：记录 warning，不阻塞服务启动。
- reranker warmup 失败：记录 warning，不阻塞服务启动。
- 实时 reranker 超时：fallback 到确定性候选选择，trace 标记 `reranker_timeout`。
- 实时 reranker worker 崩溃或返回非法 JSON：fallback 到确定性候选选择，trace 标记 `reranker_unavailable`。
- Milvus 不可用：沿用现有 `milvus_unavailable` 跳过逻辑。
- 高风险用户输入：沿用现有风险策略，不进入 RAG。

## 可观测性

每轮 RAG trace 至少保留：

- `embedding_duration_ms`
- `milvus_duration_ms`
- `rerank_duration_ms`
- `rerank_status`
- `rerank_reason`
- `rerank_candidate_count`
- `rerank_model_candidate_count`
- `rerank_timeout_ms`
- `total_duration_ms`

启动日志至少保留：

- embedding warmup 是否完成、耗时、device。
- reranker warmup 是否完成、耗时、reason。

## 测试策略

### 单元测试

新增或更新 `backend/tests/test_counseling_milvus_plan.py`：

- 验证模型 reranker 只接收前 `COUNSELING_RERANK_TOP_N` 条候选。
- 验证 trace 包含 `rerank_candidate_count` 和 `rerank_model_candidate_count`。
- 验证 rerank timeout 使用 `min(RAG 剩余时间, COUNSELING_RERANK_TIMEOUT_SECONDS)`。
- 验证 timeout 后返回 fallback 示例且 trace reason 为 `reranker_timeout`。

新增或更新 `backend/tests/test_startup_script.py`：

- 验证 `scripts/start-backend.ps1` 默认注入 `LOCAL_EMBEDDING_WARM_ON_STARTUP`。
- 验证 `scripts/start-backend.ps1` 默认注入 `COUNSELING_RERANK_WARM_ON_STARTUP`。
- 验证 `scripts/start-backend.ps1` 默认注入 `COUNSELING_RERANK_TIMEOUT_SECONDS=5`。
- 验证 dry-run 输出包含这些关键环境变量。

新增或更新 main/startup 相关测试：

- 验证配置项 `COUNSELING_RERANK_WARM_ON_STARTUP` 能被加载。
- 验证 startup 在开启配置时会创建 reranker warmup task。
- 验证 shutdown 会关闭 reranker worker。

### 手工验证

启动本地全套环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

执行一次本地流式诊断：

- 记录 `first_graph_update_ms`。
- 记录 `first_token_ms`。
- 记录 final trace 中 `rerank_duration_ms`、`rerank_reason`、`rerank_model_candidate_count`。

验收标准：

- 首轮 `first_token_ms < 8000`。
- warm 后 `first_token_ms < 5000`。
- RAG trace `status` 为 `hit` 或可解释 fallback。
- 没有 `stream_failed`。

## 发布和回滚

发布顺序：

1. 先合入配置、trace 和 fallback 测试。
2. 再合入启动脚本默认值。
3. 本地验证后更新 dev-log。

回滚方式：

- 若 reranker fallback 质量不可接受，可以把 `COUNSELING_RERANK_TIMEOUT_SECONDS` 调回 20。
- 若 warmup 影响启动资源，可以把 `COUNSELING_RERANK_WARM_ON_STARTUP=0`。
- 若候选裁剪影响质量，可以增大 `COUNSELING_RERANK_TOP_N`。

## 风险

- CPU reranker 即使只处理 12 条候选，也可能在低性能机器上超过 5 秒，因此 timeout fallback 必须是正常路径。
- fallback 示例质量低于模型重排，需要 trace 明确暴露，便于后续评价。
- 预热任务会增加启动后短时间 CPU 和内存占用，但不应阻塞 `/health`。
- 如果用户连续发送多轮，reranker worker 的锁会串行处理请求，本轮不解决并发队列问题。

## 默认决策

- 本地默认 `COUNSELING_RERANK_TIMEOUT_SECONDS=5`。
- 本轮保持 `COUNSELING_RERANK_TOP_N=12`，不先降到 8。
- 接受 fallback 作为低延迟实时对话的正常路径，前提是 trace 明确暴露 `rerank_reason`。
