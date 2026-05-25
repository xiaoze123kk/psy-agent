# 澄清闭环与记忆冲突仲裁设计

## 背景

当前系统已经能在“继续”“这个”这类低信息输入且缺少上下文时触发澄清，也能写入 `correction` 类型记忆。但澄清回答还没有被显式绑定回下一轮目标状态；当长期记忆里同时存在旧偏好和新的纠错记忆时，也缺少稳定的冲突仲裁路径。

## 目标

1. 当上一轮助手发出澄清问题，下一轮用户回答时，把用户回答识别为“澄清答案”，写入 `goal_state`，并参与本轮记忆检索。
2. 在长期记忆检索中，当 `correction` 与 `preference`/`support_strategy` 等旧记忆冲突时，优先采用更新、更明确的纠错记忆。
3. 写入新的 `correction` 候选时，对同用户下可能冲突的旧偏好记忆做轻量标记，避免旧记忆继续强势影响回复。

## 非目标

- 不改数据库结构，不新增迁移。
- 不引入 LLM 判断冲突，先使用保守规则和分数仲裁。
- 不删除旧记忆，只做 `needs_review` 标记和检索降权，方便后续用户审核。

## 方案

### 澄清闭环

- 在 `GraphRuntime._map_result()` 和 `chat_service` 的 assistant metadata 中保留 `clarification_needed`、`clarification_reason` 和 `control_category`。
- `build_goal_state()` 新增 `recent_messages` 参数，检查最近一条助手消息是否是澄清问题。
- 如果当前输入不是空泛短语，则把当前输入压缩成：
  - `current_goal`: `用户澄清当前想谈：...`
  - `clarification_answer`: 用户原始澄清回答
  - `clarification_reason`: 上一轮澄清原因
- 记忆检索查询拼接 `clarification_answer`，使“主管那件事”这类短回答能召回目标、纠错和相关主题记忆。
- `memory_candidate_extract()` 在 long_term 模式下，如果看到 `clarification_answer`，生成一个 `goal` 候选，把澄清结果沉淀到长期目标线索。

### 记忆冲突仲裁

- 检索评分新增冲突仲裁：
  - `correction` 在当前查询或目标状态涉及“不要/别/先听/不是这个意思”等纠错信号时额外加权。
  - `preference`、`support_strategy` 在同一场景下被轻度降权，避免旧偏好盖过明确纠错。
  - `needs_review` 记忆检索降权，但不彻底隐藏。
- 写入新的 `correction` 记忆后，扫描同用户可见的 `preference` 和 `support_strategy` 记忆；若关键词明显冲突，把旧记忆标记为 `needs_review`，并在 `structured_value.memory_conflict` 中记录新纠错记忆 id、时间和原因。
- 每次标记都写入 `MemoryOperation(action="feedback")`，便于审计。

## 测试策略

- `user_context_service`：上一轮澄清后，下一轮短回答能生成带 `clarification_answer` 的 `goal_state`。
- `chat_service`：准备上下文时会把上一轮澄清 metadata 传入 `build_goal_state()`，并让 fake runtime 收到绑定后的 `goal_state`。
- `memory_nodes`：澄清答案会产生 `goal` 候选。
- `memory_service`：冲突场景下 `correction` 排在旧 `preference` 前；写入新的 `correction` 后，旧冲突偏好被标记 `needs_review`。
- 回归：运行连续性与记忆相关最小集合，最后跑本轮相关回归集合。
