# 记忆系统分析文档

## 一、架构总览

记忆系统由 8 个协同子系统组成，采用**混合双存储**架构：PostgreSQL 负责结构化元数据，Milvus 负责语义向量检索。写入路径为异步 job 队列模式，读取路径为同步混合检索。

### 系统组成

| 子系统 | 文件 | 职责 |
|--------|------|------|
| 记忆提取层 | `app/graphs/nodes/memory_nodes.py` | 从对话中提取候选记忆 |
| 记忆写入服务 | `app/services/memory_service.py` | 去重、可见性控制、持久化 |
| 异步任务服务 | `app/services/memory_job_service.py` | 后台 job 调度与执行 |
| 记忆检索服务 | `app/services/memory_service.py` | 混合评分检索 |
| 向量索引服务 | `app/services/memory_service.py` | 嵌入生成与 Milvus 双写 |
| 向量存储 | `app/services/milvus_service.py` | Milvus HNSW+COSINE 检索 |
| 嵌入提供者 | `app/services/embedding_service.py` | BGE-M3 本地 / DashScope API |
| 整合引擎 | `app/services/memory_service.py` | 去重、过期、情绪状态生成 |

### 数据流

```
写入链路:
  对话轮次结束
    → memory_candidate_extract (关键词提取候选记忆)
    → build_memory_job_payload (序列化为 job)
    → enqueue_memory_job (写入 PendingMemoryJob 队列)
    → 后台 Worker 轮询
      → upsert_memory_candidates (去重 + 写入 user_memories 表)
      → index_memory_embeddings (向量化 + 写入 memory_embeddings 表 + Milvus)
      → maybe_auto_consolidate (条件触发整合)

读取链路:
  用户发送消息
    → retrieve_memories_for_turn_async (异步入口)
    → _base_memory_query (PG 查最多 200 条活跃记忆)
    → _memory_ids_from_vector_hits (Milvus COSINE 检索, limit*4 过采样)
    → 候选合并 (按 ID 去重)
    → _score_memory (词法评分) + _vector_score_memory (向量评分)
    → 取 max(词法分, 向量分)
    → Top-5 记忆注入 LLM prompt
```

---

## 二、数据模型

### 8 种记忆类型

| 类型 | 中文名 | 可见性 | 写入模式门控 | 失效 |
|------|--------|--------|-------------|------|
| `profile` | 基础画像 | user_visible | long_term | 否 |
| `preference` | 陪伴偏好 | user_visible | long_term | 否 |
| `session_summary` | 对话摘要 | user_visible | summary_only+ | 否 |
| `recurring_trigger` | 触发点 | user_visible | long_term | 否 |
| `support_strategy` | 支持方式 | user_visible | long_term | 否 |
| `relationship` | 关系记忆 | user_visible | long_term | 否 |
| `state` | 长期状态 | user_visible | long_term (整合生成) | 否 |
| `safety_summary` | 安全摘要 | internal_safety | 始终允许 | 否 |

> `goal` 类型在类型列表中定义但无创建代码路径，属于死代码。

### 5 张核心表

| 表 | 用途 |
|----|------|
| `user_memories` | 记忆主体（28 字段含 UUID、类型、内容、重要性、置信度、可见性、审查状态、版本号、TTL） |
| `memory_embeddings` | 嵌入向量 PG 副本（JSON 格式存 float 数组） |
| `memory_operations` | 操作审计日志（动作、前后快照、原因、执行者） |
| `memory_consolidation_runs` | 整合任务执行记录 |
| `pending_memory_jobs` | 异步写入队列（含 worker 锁机制） |

### Milvus 集合

`user_memories_v1` 集合配置：

| 参数 | 值 |
|------|-----|
| 索引类型 | HNSW |
| 度量方式 | COSINE |
| 维度 | 1024 |
| M | 16 |
| efConstruction | 200 |
| ef (搜索) | 64 |
| 主键 | id (VARCHAR 128, UUID) |
| 标量字段 | memory_id, user_id, memory_type, visibility, status, review_state, title, source, embedding_key, updated_at |
| 内容字段 | content (VARCHAR 8192) |

---

## 三、写入路径详解

### 3.1 记忆提取（Graph 节点）

`memory_candidate_extract()` 节点根据用户的 `memory_mode` 执行不同策略：

- **long_term 模式**：在用户消息中检查关键词子串（如 "喜欢"、"经常"、"我叫"、"呼吸"），匹配后生成对应类型的候选记忆，最多 8 条
- **summary_only 模式**：仅生成 `session_summary` 类型
- **off 模式**：不生成候选

**缺陷**：使用纯子串匹配（`has_any_text`），"我不喜欢" 也会触发 `preference` 类型提取，语义完全相反。

### 3.2 写入门控

`upsert_memory_candidates()` 在多个层级进行门控：

1. `should_write_memory` 标识（来自 LLM 判断）
2. `memory_mode` 检查 — off 阻止所有非安全类写入
3. `risk_level` 检查 — L2/L3 只允许 `safety_summary`
4. `memory_policy` — skip_sensitive 仅在 L2/L3 时写入
5. `_unsafe_visible_memory_reason()` — 拦截含敏感词的可见记忆

### 3.3 去重逻辑

`_find_similar_memory()` 对每条候选记忆执行：

1. 查询同用户同类型同可见性的最多 50 条记忆
2. 先检查完全相同的 content
3. 再用 `SequenceMatcher` 计算内容相似度，阈值 0.88
4. 命中则更新现有记忆（合并 tags、取 max importance、递增版本号），未命中则新建

### 3.4 向量索引

`index_memory_embeddings()` 在写入后异步执行：

1. 调用 `EmbeddingClient.embed_texts()` 批量生成嵌入
2. 逐条查询 `MemoryEmbedding` 表检查是否已有嵌入
3. 将向量写入 `MemoryEmbedding` 表（PG JSON 列）
4. 将向量写入 Milvus `user_memories_v1` 集合

### 3.5 异步 Job 系统

`memory_job_service.py` 实现后台 worker：

- **轮询间隔**：2 秒（可配置）
- **批大小**：5 个 job（可配置）
- **最大重试**：3 次（可配置）
- **退避策略**：指数退避 `min(60, 2^(attempt-1))` 秒
- **唤醒机制**：新 job 入队时通过 `asyncio.Event` 立即唤醒
- **worker 锁**：`locked_at` + `locked_by`（hostname）防止多 worker 冲突

---

## 四、读取路径详解

### 4.1 查询构建

`_query_for_retrieval()` 拼接以下内容（截断至 1200 字符）：
- 用户当前输入
- 上次对话摘要
- 控制类别
- 最近 4 条消息

此查询文本同时用于词法评分和向量检索。

### 4.2 基础查询

`_base_memory_query()` 从 PG 查询最多 200 条活跃记忆，按 `importance DESC, updated_at DESC` 排序，过滤条件：
- `review_state != "do_not_use"`
- `expires_at IS NULL OR expires_at > now`
- 无 `memory_type` 过滤（在应用层过滤）

### 4.3 向量检索

`_memory_ids_from_vector_hits()` 调用 Milvus 搜索，`limit = max(user_limit * 4, 20)`（即请求 5 条时实际查询 20 条做过采样）。过滤条件：
- `user_id == "..."`（跨用户隔离）
- `status == "active"`
- `embedding_key == "..."`
- `review_state != "do_not_use"`
- 根据 mode 和 risk 附加 visibility/type 过滤

### 4.4 混合评分

#### 词法评分

```
score = 0.46 * term_similarity
      + 0.28 * importance_score
      + 0.12 * freshness_score
      + 0.06 * access_score
      + type_boost
```

- `term_similarity` = 查询词与记忆词的共享 token 数 / 查询 token 数
- `importance_score` = importance / 5
- `freshness_score` = max(0, 1 - min(age_days, 90) / 90)
- `access_score` = min(access_count, 10) / 10
- `type_boost` = 0.03 ~ 0.08（关键词触发）

#### 向量评分

```
score = 0.62 * normalized_vector_score
      + 0.18 * importance_score
      + 0.10 * freshness_score
      + 0.04 * access_score
      + type_boost
```

- `normalized_vector_score` = COSINE 距离线性映射到 [0, 1]

#### 最终选择

取 **max(词法分, 向量分)**，用较高分对应的评分原因。

### 4.5 风险等级门控

| 风险等级 | 可读记忆 | 可写记忆 |
|----------|---------|---------|
| L0/L1 (正常) | 全部 user_visible 类型 | 根据 memory_mode |
| L2/L3 (危机) | 仅 safety_summary (internal_safety) | 仅 safety_summary |

---

## 五、记忆整合

`consolidate_user_memories()` 在写入后条件触发（距上次 > 24h 且新增 ≥ 5 个会话），执行三个子操作：

### 5.1 过期清理

将 `expires_at` 已过期的活跃记忆设为 `status = "expired"`。

### 5.2 去重合并

按类型分组，组内 O(n²) 比较（`SequenceMatcher`，阈值 0.90），合并相似记忆：
- 保留 importance 更高者
- 合并 tags
- 另一条标记为 `status = "deleted"`

### 5.3 情绪状态生成

最近 14 天内 ≥ 3 条 MoodLog 则生成/更新 `state` 类型记忆，内容包含平均情绪分和 Top-5 标签。

### 5.4 并发防护

检查最近 1 小时内是否存在 "running" 状态的整合运行，存在则跳过（非 force 模式）。

---

## 六、API 端点

基础路径：`/api/v1/memories`

| 方法 | 路径 | 说明 | 问题 |
|------|------|------|------|
| GET | `/memories` | 列出用户可见记忆 | 无分页，一次返回全部 |
| POST | `/memories/search` | 混合搜索记忆 | limit 无上下界校验 |
| GET | `/memories/audit` | 操作审计日志 | 内部上限 200，无分页 |
| POST | `/memories/consolidate` | 手动触发整合 | 与 service 事务分离 |
| POST | `/memories/{id}/feedback` | 记忆反馈 | feedback 字段自由文本 |
| PATCH | `/memories/{id}` | 编辑记忆 | summary 硬截断 180 字符 |
| DELETE | `/memories/{id}` | 软删除单条记忆 | 不清理 Milvus 向量 |
| DELETE | `/memories` | 清空所有可见记忆 | 不清理 Milvus 向量 |
| GET | `/memories/document` | 导出 Markdown 文档 | 可能生成超大文档 |

反馈选项：`accurate`（置信度 +0.1）、`inaccurate`（置信度 -0.2）、`dont_use`（软删除）。

---

## 七、Bug 清单

### CRITICAL

#### 1. Milvus/PG 状态不同步
- **位置**：`memory_service.py` 整合去重、过期清理、反馈删除
- **现象**：以上操作在 PG 中更新 `status` 但不同步到 Milvus。被删除记忆的向量仍在 Milvus 中标记为 `active`，浪费检索带宽并可能泄露已删除内容。
- **影响**：每次搜索都可能返回无效结果，需应用层二次过滤。

#### 2. Job 卡死风险
- **位置**：`memory_job_service.py` 第 226-233 行
- **现象**：`process_memory_job` 在处理非 "running" 状态 job 时先 commit 状态变更，后续处理失败触发 rollback 但状态已持久化，job 永远停在 "running"。
- **触发条件**：job 状态被外部修改 + 处理过程报错。

#### 3. 去重匹配已删除记忆
- **位置**：`memory_service.py` `_find_similar_memory()` 第 629 行
- **现象**：去重查询没有 `status == "active"` 过滤，可能匹配到已删除/已过期记忆，导致新记忆被合并到无效记录上。
- **影响**：新记忆无法正常写入，丢失数据。

### HIGH

#### 4. Job 领取竞态条件
- **位置**：`memory_job_service.py` `claim_pending_memory_jobs()`
- **现象**：用 `status == "pending"` 做乐观锁而非 `SELECT ... FOR UPDATE SKIP LOCKED`，并发 worker 可能领取同一 job。
- **修复**：使用 PostgreSQL 行级锁。

#### 5. MemoryEmbedding N+1 查询
- **位置**：`memory_service.py` `index_memory_embeddings()`
- **现象**：每条记忆执行一次 `scalar(select())` 查询 MemoryEmbedding 表，8 条记忆 = 8 次查询。
- **修复**：改为 `select().where(MemoryEmbedding.memory_id.in_(ids))`。

#### 6. Milvus 写入失败静默吞掉
- **位置**：`memory_service.py` 第 867 行 `except Exception: pass`
- **现象**：Milvus upsert 失败不重试不告警，记忆已写 PG 但向量索引永久缺失。
- **修复**：增加重试机制和告警。

#### 7. 整合去重 O(n²) 复杂度
- **位置**：`memory_service.py` `_consolidate_duplicate_memories()`
- **现象**：同类型内全量两两 `SequenceMatcher` 比较，100 条 = 4950 次。
- **修复**：先用词集合重叠或长度比做快速预筛。

### MEDIUM

#### 8. 基础查询不做类型过滤
- `_base_memory_query()` 始终查 200 条，`summary_only` 模式下 199 条被丢弃。
- **修复**：添加可选的 `memory_types` 参数做 DB 层过滤。

#### 9. 关键词提取语义不准确
- 子串匹配 `"我不喜欢"` 也会触发 `preference` 提取。
- **修复**：引入否定词检测或使用 LLM 判断。

#### 10. 嵌入查询混入干扰信息
- 查询文本拼接了最近 4 条消息，稀释当前查询语义信号。

#### 11. 评分算法的 max 策略缺陷
- 短查询词法分容易膨胀，与查询词汇重叠多但语义无关的记忆会战胜语义相关但词汇不同的记忆。

#### 12. 情绪状态阈值过低
- 14 天内仅 3 条 MoodLog 即生成状态，数据可能已过时。

### LOW

#### 13. `goal` 类型死代码
- 在类型列表中定义但无任何创建路径。

#### 14. API 缺少分页
- 列表/审计/文档导出均无分页支持。

#### 15. feedback 字段无校验
- 拼写错误（如 "accuarte"）会静默创建无意义的 review_state。

---

## 八、性能瓶颈

| 瓶颈 | 位置 | 影响 | 优先级 |
|------|------|------|--------|
| 每轮查 200 条基础记忆 | `_base_memory_query` | summary_only 模式 99.5% 被丢弃 | MEDIUM |
| N+1 MemoryEmbedding 查询 | `index_memory_embeddings` | 逐条查嵌入表 | HIGH |
| O(n²) 整合去重 | `_consolidate_duplicate_memories` | 100 条同类型 = 4950 次 SequenceMatcher | HIGH |
| 候选去重逐条查询 | `_find_similar_memory` | 8 候选×50 行 = 最多 400 次 SequenceMatcher | MEDIUM |
| DashScope 批大小硬编码 | `embedding_service.py` | 批大小固定 10，可能未达最优 | LOW |
| Milvus REST API 往返 | `milvus_service.py` | 每次搜索 HTTP POST，首次查询需加载 collection schema | LOW |

---

## 九、安全问题

### 9.1 PII 检测不完整
- `UNSAFE_VISIBLE_TERMS` 仅 16 个词，缺少 "电话号码"、"地址"、"邮箱"、"微信"、"QQ" 等常见 PII 变体
- 英文大小写已处理，但代码混合文本可能漏检

### 9.2 嵌入向量未加密
- `MemoryEmbedding.embedding` 以 JSON 明文存于 PG，存在嵌入逆向攻击重建原文的风险
- 这是已知的嵌入模型安全问题

### 9.3 读取审计粒度粗
- 只有批量操作日志，缺乏"某用户在何时读取了哪条具体记忆"的逐条追踪
- `access_count` 仅计数不记时间戳

### 9.4 跨用户隔离（当前正确）
- 所有操作均通过 `user_id` 隔离
- Milvus 搜索也在 filter 中包含 `user_id`
- 暂无跨用户数据泄露风险

---

## 十、改进建议

### 架构层面

1. **实现 Milvus 同步清理**：记忆删除/过期/去重后，同步删除 Milvus 中的对应向量
2. **添加 DB 层类型过滤**：基础查询支持 `memory_types` 参数减少无效行加载
3. **使用行级锁**：job 领取改为 `SELECT ... FOR UPDATE SKIP LOCKED`
4. **创建独立的 Milvus 清理函数**：`remove_memory_vectors(memory_ids: list[str])`

### 可靠性

5. **修复 job 卡死 bug**：不要在 `process_memory_job` 中间 commit 状态
6. **Milvus 写入增加重试**：替换 `except Exception: pass` 为指数退避重试
7. **`_find_similar_memory` 添加 `status == "active"` 过滤**：防止匹配到已删除记忆

### 性能

8. **批量查询 MemoryEmbedding**：`WHERE memory_id IN (...)` 替代逐个 scalar
9. **列表端点增加分页**：支持 offset/limit 或游标分页
10. **SequenceMatcher 前增加预筛**：用词集重叠或长度比快速排除不可能匹配的候选项

### 代码质量

11. **移除 dead code**：`goal` 类型要么实现要么删除
12. **API 输入增加校验**：`limit` 设上下界，`feedback` 改用枚举
13. **关键函数添加 docstring**：`retrieve_memories_for_turn`、`upsert_memory_candidates`、`consolidate_user_memories`
14. **添加基础指标**：检索延迟、记忆命中率、向量搜索召回率、job 队列深度
15. **添加一致性检查**：定期对比 Milvus 活跃向量数与 PG 活跃记忆嵌入数

### 测试

16. **评分算法单元测试**：用已知输入验证排序结果
17. **竞态条件集成测试**：job 领取和整合的并发场景
18. **Milvus 降级行为测试**：Milvus 不可用时退回纯词法检索的完整性

---

## 十一、配置参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MEMORY_BACKGROUND_WORKER_ENABLED` | 1 | 后台 worker 开关 |
| `MEMORY_JOB_BATCH_SIZE` | 5 | 每次领取 job 数量 |
| `MEMORY_JOB_MAX_ATTEMPTS` | 3 | job 最大重试次数 |
| `MEMORY_JOB_POLL_INTERVAL_SECONDS` | 2 | worker 轮询间隔 |
| `MILVUS_ENABLED` | 0 | Milvus 向量检索开关 |
| `MILVUS_URI` | http://localhost:19530 | Milvus 地址 |
| `MILVUS_COLLECTION_PREFIX` | psych_agent | 集合名前缀 |
| `EMBEDDING_PROVIDER` | local | 嵌入服务 (local / dashscope) |
| `EMBEDDING_MODEL` | BAAI/bge-m3 | 嵌入模型 |
| `EMBEDDING_DIM` | 1024 | 嵌入维度 |
| `COUNSELING_RAG_ENABLED` | 0 | 咨询语料 RAG 开关 |
