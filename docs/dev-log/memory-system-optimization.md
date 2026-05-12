# 记忆系统优化迭代日志

## 2026-05-12

### 背景

本轮迭代基于 `docs/memory-system-analysis.md` 的问题分析展开，优先处理记忆写入链路中风险明确、改动边界清晰的问题。优化原则是：不改对外 API、不调整数据库结构、不重写记忆评分策略，只在现有服务层内收敛失败恢复和相似记忆匹配成本。

关联资料：

- `docs/memory-system-analysis.md`
- `docs/superpowers/specs/2026-05-12-memory-system-optimization-design.md`
- `docs/superpowers/plans/2026-05-12-memory-system-optimization.md`

### 已完成改动

#### 1. Memory job 失败路径恢复

- `process_memory_job()` 在处理非 `running` job 时不再中途 `commit()`，避免业务逻辑失败后把 `running` 状态提前持久化。
- 失败路径仍通过 `_mark_job_failed()` 写回最终 `pending` / `failed` 状态、锁释放信息和错误元数据。
- 新增回归测试，覆盖 memory job 处理异常后不会出现多余中间提交。

#### 2. 相似记忆匹配过滤

- `_find_similar_memory()` 继续保留 `user_id`、`status == "active"`、`memory_type`、`visibility` 过滤。
- 新增 `review_state != "do_not_use"` 过滤，避免写入时合并到已标记不可使用的记忆。
- 新增 `expires_at is null OR expires_at > now` 过滤，避免新候选记忆合并到已过期记忆。
- 保留精确匹配快速路径和 `0.88` 相似度阈值。

#### 3. 相似度计算预筛

- 新增 `_should_compare_memory_content()`，在调用 `SequenceMatcher` 前先做低成本判断。
- 空内容直接跳过，完全相同内容直接进入匹配。
- 长短文本比例低于 `0.45` 时跳过，减少明显不相关文本的相似度计算。
- 短文本保留比较机会；普通文本要求 token 集合存在交集后才进入 `_content_similarity()`。
- 新增回归测试，确认无关候选会被预筛，同时相近内容仍可正常合并。

### 验证结果

在 `backend/` 目录执行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py::MemoryServiceTests::test_upsert_ignores_expired_memory_when_finding_similar_match tests/test_memory_service.py::MemoryServiceTests::test_upsert_ignores_do_not_use_memory_when_finding_similar_match tests/test_memory_service.py::MemoryServiceTests::test_find_similar_memory_prefilter_skips_unrelated_candidates tests/test_memory_service.py::MemoryServiceTests::test_find_similar_memory_prefilter_still_allows_similar_merge tests/test_memory_service.py::MemoryServiceTests::test_upsert_merges_duplicates_and_records_metadata tests/test_memory_service.py::MemoryServiceTests::test_upsert_blocks_sensitive_visible_and_allows_high_risk_safety_summary -v
```

结果：`6 passed`。

继续执行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py -q
```

结果：`14 passed`。

最终执行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py -q
```

结果：`32 passed, 1 warning`。warning 来自 LangGraph / LangChain 的 pending deprecation warning，非本轮改动引入。

### 相关提交

| Commit | 内容 |
|---|---|
| `7b06550` | 修复 memory job 失败路径中间提交问题 |
| `b653ba0` | 增加相似记忆过滤和预筛回归测试 |
| `ef749eb` | 实现相似记忆匹配过滤与预筛 |

### 未纳入本轮

以下问题仍留作后续迭代：

- `_base_memory_query()` 的 memory type SQL 下推过滤。
- `index_memory_embeddings()` 的批量查询优化。
- Milvus 与 PostgreSQL 中删除 / 过期状态的同步清理。
- `claim_pending_memory_jobs()` 的多 worker 行级锁竞争处理。
- Milvus upsert 失败后的重试和可观测性。

### 结论

本轮完成了两类低耦合优化：memory job 失败恢复更稳，相似记忆去重更安全也更省计算。写入链路不会再把新记忆合并到已过期或不可使用的旧记忆上，同时明显无关候选会在进入 `SequenceMatcher` 前被跳过。
