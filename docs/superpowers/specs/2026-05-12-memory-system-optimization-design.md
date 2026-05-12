# 记忆系统优化设计

## 动机

`docs/memory-system-analysis.md` 里列出的几个高优先级问题，集中在三类：

1. 后台记忆 job 在失败路径上可能卡在 `running`
2. 记忆检索的基础查询先取 200 条再在 Python 里过滤，浪费行数预算
3. `index_memory_embeddings()` 对每条记忆单独查一次 `MemoryEmbedding`，形成 N+1 查询

这轮只做低耦合、可验证的优化，先把可靠性和明显性能浪费收紧。

## 设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| job 状态推进 | `claim_pending_memory_jobs()` 负责领取和持久化 `running`；`process_memory_job()` 只执行已领取 job，失败后用独立回写事务落最终状态 | 避免 job 在异常时停在 `running` |
| 基础查询过滤 | `_base_memory_query()` 增加可选 `memory_types` 参数，把类型过滤下推到 SQL | 减少无效行读取，尤其是 `summary_only` 和高风险检索 |
| 嵌入查询 | `index_memory_embeddings()` 先批量拉取已有 `MemoryEmbedding`，再循环更新/新增 | 消除 N+1 查询，保持现有写入语义 |
| 范围控制 | 不改 API 结构、不做 Milvus 删除同步、不碰分页和反馈枚举 | 把这轮控制在服务层优化 |

## 改动范围

| 文件 | 改动 |
|------|------|
| `backend/app/services/memory_job_service.py` | 调整 `process_memory_job()` 的事务边界和失败回写路径 |
| `backend/app/services/memory_service.py` | `_base_memory_query()` 增加类型过滤；`build_memory_index()` / `retrieve_memories_for_turn()` 传入允许类型；`index_memory_embeddings()` 改成批量查询 |
| `backend/tests/test_memory.py` | 补 job 失败不应卡在 `running` 的回归测试 |
| `backend/tests/test_memory_service.py` | 补 `summary_only` 类型过滤测试和批量嵌入查询测试 |

## 详细设计

### 1. Job 处理不再中途提交

`claim_pending_memory_jobs()` 继续负责领取 job 并把状态落到 `running`。`process_memory_job()` 只处理已经领取的 job，不再承担补领或中途提交职责。

处理流程保持单向：

1. 读取已领取的 job
2. 执行业务写入
3. 成功后统一提交
4. 任何异常发生后先 `rollback`，再通过 `_mark_job_failed()` 重新持久化 `pending` 或 `failed`

这样失败时不会留下一个已经提交的 `running` 状态。retry 逻辑仍然沿用现有的 `attempt_count` 和指数退避。

### 2. 基础查询把类型约束下推到数据库

`_base_memory_query(db, user_id, memory_types=None)` 保持现有的：

- `status == "active"`
- `review_state != "do_not_use"`
- `expires_at` 未过期
- 按 `importance DESC, updated_at DESC`
- 仍然限制 200 条

当 `memory_types` 提供时，再追加 `UserMemory.memory_type.in_(...)`。如果传入空集合，直接返回空结果，避免构造无效 `IN ()`。

调用方调整：

- `build_memory_index()` 按当前 `memory_mode` / `include_internal` 传入允许类型
- `retrieve_memories_for_turn()` 按 `allowed_types` 传入允许类型

这不会改变排序或可见性规则，只是让数据库少吐无关行。

### 3. 嵌入索引改成一次批量查询

`index_memory_embeddings()` 仍然：

- 先筛出有内容、且状态为 `active` 的记忆
- 调用 embedding 服务批量生成向量
- 组装 Milvus 写入行

变化点是：它不再对每条记忆单独执行 `db.scalar(select(MemoryEmbedding)...)`，而是一次性查出当前 `embedding_key` 下这些 `memory_id` 的已有记录，再在内存里按 `memory_id` 建映射更新。

因为 `memory_embeddings` 表目前没有唯一约束，这个批量查询按“同一 `memory_id` 下最新记录优先”的方式归并，保持行为稳定，不额外引入表结构改动。

Milvus upsert 的现有逻辑、失败吞掉行为、`db.flush()` 时机本轮都不动。

## 测试策略

### `backend/tests/test_memory.py`

新增一个 job 回归测试，覆盖：

- 创建一个待处理的 memory job
- 人为注入 `upsert_memory_candidates()` 或 `index_memory_embeddings()` 异常
- 调用 `process_pending_memory_jobs()`
- 断言 job 最终不是 `running`
- 断言失败信息和重试状态被写回

### `backend/tests/test_memory_service.py`

新增两个测试：

1. `summary_only` 场景下创建 200 条高排序的非摘要记忆，再加 1 条 `session_summary`，验证 `build_memory_index()` 仍能返回摘要
2. `index_memory_embeddings()` 在多条记忆写入时只做一次批量 `MemoryEmbedding` 读取，同时仍然会更新/新增正确的记录

批量查询测试优先用 SQL 事件计数，而不是直接绑死在具体 ORM 调用上，这样能证明“只查一次”这个行为本身。

## 非目标

- 不做 Milvus 删除同步
- 不做 API 分页
- 不改 `feedback` 枚举校验
- 不重写记忆评分算法
- 不调整记忆文档导出格式

## 验收标准

- job 失败后不会永久停在 `running`
- `summary_only` 检索不会因为前 200 条无关高重要度记忆而丢掉摘要
- `index_memory_embeddings()` 不再出现按条查嵌入表的 N+1 行为
- 现有记忆检索和写入测试保持通过
