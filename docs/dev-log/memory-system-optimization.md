# 记忆系统优化迭代日志

## 2026-05-12

### 背景

本轮迭代基于 `docs/memory-system-analysis.md` 的问题分析展开，优先处理记忆写入与检索链路中风险明确、收益清晰的优化项。不改对外 API，不调整数据库结构，只在现有服务层内收敛失败恢复、查询浪费和相似记忆匹配成本。

关联资料：

- `docs/memory-system-analysis.md`
- `docs/superpowers/specs/2026-05-12-memory-system-optimization-design.md`
- `docs/superpowers/plans/2026-05-12-memory-system-optimization.md`

### 已完成改动

#### 1. Memory job 失败路径恢复

- `process_memory_job()` 在处理非 `running` job 时不再中途 `commit()`。
- 失败路径仍通过 `_mark_job_failed()` 写回最终 `pending` / `failed` 状态、锁信息和错误元数据。
- 新增回归测试，覆盖 memory job 异常后不会提前提交 `running` 状态。

#### 2. 相似记忆匹配过滤与预筛

- `_find_similar_memory()` 继续保留 `user_id`、`status == "active"`、`memory_type`、`visibility` 过滤。
- 新增 `review_state != "do_not_use"` 过滤，避免合并到不可使用的记忆。
- 新增 `expires_at is null OR expires_at > now` 过滤，避免合并到已过期记忆。
- 新增 `_should_compare_memory_content()`，在进入 `SequenceMatcher` 前先做低成本预筛。
- 新增回归测试，确认无关候选会被跳过，近似内容仍可正常合并。

#### 3. MemoryEmbedding 批量查询

- `index_memory_embeddings()` 先一次性加载已有 `MemoryEmbedding`，按 `memory_id` 建映射。
- 循环内不再逐条 `SELECT`，直接复用缓存记录。
- Milvus upsert 和最终 `db.flush()` 行为保持不变。
- 新增回归测试，确认多条记忆写 embedding 时只会查询一次 `memory_embeddings`。

#### 4. 记忆类型过滤下推

- `_base_memory_query()` 新增可选 `memory_types` 参数，并把 `UserMemory.memory_type.in_(...)` 下推到 SQL。
- 当允许类型集合为空时，直接返回空结果查询，避免构造无效的 `IN ()`，同时保持 helper 的返回形状一致。
- `build_memory_index()` 与 `retrieve_memories_for_turn()` 不再在 Python 层二次过滤记忆类型。
- 新增 `summary_only` 回归测试，确认 200 条高优先级 `preference` 记忆不会挤掉唯一的 `session_summary`。

#### 5. Milvus 向量同步清理

- `MilvusVectorStore` 新增 `delete_memory_vectors()`，按记忆主键删除 `user_memories` 向量集合中的对应记录。
- `memory_service.remove_memory_vectors()` 作为安全包装，统一处理空列表、去重和异常日志。
- 记忆整合时被合并删除的重复记忆、TTL 过期记忆会同步清理 Milvus 向量。
- 用户手动删除、清空可见记忆、反馈 `dont_use`、隐私清理和聊天数据清理也会同步移除对应向量。
- 新增回归测试，确认整合任务和清空可见记忆会调用向量删除，并且不会删除内部安全记忆向量。

#### 6. Milvus upsert 失败重试与可观测性

- `index_memory_embeddings()` 新增最多 3 次的 Milvus upsert 重试，避免临时写入失败直接吞掉整批记忆向量。
- 重试结束后会记录包含 `memory_ids` 的告警日志，便于回溯具体失败记忆。
- 新增回归测试，确认 Milvus 写入失败时会重试 3 次并输出告警日志。

### 验证结果

在 `backend/` 目录执行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py -q
```

结果：`42 passed, 2 warnings`。

warnings 来自 LangGraph / LangChain 的 pending deprecation warning，以及 SQLAlchemy model 类名被 pytest 尝试收集的既有提示，非本轮改动引入。

在 `backend/` 目录追加执行：
```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_memory.py tests/test_privacy.py -q
```

结果：`43 passed, 2 warnings`。warnings 仍来自 LangGraph / LangChain 的既有提示，以及 SQLAlchemy model 类名被 pytest 尝试收集的既有提示。
### 相关提交

| Commit | 内容 |
|---|---|
| `7b06550` | 修复 memory job 失败路径中间提交问题 |
| `b653ba0` | 增加相似记忆过滤和预筛回归测试 |
| `ef749eb` | 实现相似记忆匹配过滤与预筛 |
| `87d94f5` | 稳定记忆 embedding 批量查询测试 |
| `b888056` | 优化记忆 embedding 批量查询 |
| `a03ad52` | 前置记忆类型过滤 |
| `15ef4d3` | 同步清理记忆向量 |

### 未纳入本轮

以下问题仍留作后续迭代：

- `claim_pending_memory_jobs()` 的多 worker 行级锁竞争处理。
- 记忆列表 / 审计接口分页。

### 结论

本轮完成了六类低耦合优化：memory job 失败恢复更稳，相似记忆去重更安全也更省计算，embedding 写入减少无效查询，`summary_only` 检索不再被无关高排序记忆挤掉，Milvus 向量索引会跟随删除和过期状态清理，Milvus 写入失败时也会重试并留下失败线索。写入、检索和隐私清理链路都更接近预期，且现有测试整体保持通过。
