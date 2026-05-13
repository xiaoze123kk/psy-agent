# 上下文连续性优化迭代日志

## 2026-05-12

### 背景

基于 `docs/context-continuity-design.md` 的问题分析，先把这份设计稿收敛成与当前代码现状一致、同时更适合落地执行的版本。重点是避免把 `session_digest`、多轮 messages 和工具分支升级写成“已经完成”的事实。

### 已完成改动

#### 1. 现状判断收敛

- 明确当前链路仍然是 `system + user` 的单轮输入模型。
- 明确 `recent_text`、`last_summary`、`recent_messages` 仍然是压缩上下文，不是完整对话历史。
- 明确 `last_summary` 还有多个下游读取方，不能直接替换。

#### 2. `session_digest` 设计改成“建议新增”

- 不再把 `session_digest` 写成既有事实。
- 明确它应该作为 `conversation_threads` 上新增的 JSON/JSONB 字段。
- 明确 `last_summary` 要继续保留，作为兼容短摘要或展示摘要使用。

#### 3. 多轮 messages 的范围补全

- 明确 `_model_reply_state_update` 和 `_model_reply_with_actions` 需要一起切到多轮消息。
- 明确工具分支 `run_dialogue_reply_with_tools` 也要同步升级，否则上下文会在工具场景里继续断开。
- 明确 `build_dialogue_prompt_parts` 里的 `recent_text` 只适合作为过渡兼容项。

#### 4. 检索与记忆候选提取的边界更清楚

- 明确 `_query_for_retrieval` 应优先吃结构化的会话主题字段，而不是整段原始 JSON。
- 明确 `memory_candidate_extract` 先保持保守，升级放到后续异步 worker。
- 明确这次优化不改索引结构，不改安全路由，不改 validator。

#### 5. 补上风险、回退和验收标准

- 增加 `session_digest` 迁移失败、多轮消息只改一半、digest 更新失败、prompt 变长等风险项。
- 增加 `last_summary` 回退、工具分支同步升级、digest schema 约束等回退策略。
- 增加可验收的结果描述，方便后续真正实现时对照检查。

#### 6. 会话全景持久化落地

- `ConversationThread` 新增 `session_digest` 字段。
- `GraphRuntime` 的输入/输出都透传 `session_digest`。
- `chat_service` 在完成一轮对话后会持久化 `session_digest`，同时保留 `last_summary` 作为兼容短摘要。
- `database/migrations/0014_conversation_session_digest.sql` 新增线程表迁移。

#### 7. 多轮消息回复链路

- `response_nodes` 改为将最近历史轮次作为真正的 chat messages 传给 DeepSeek。
- 工具分支 `run_dialogue_reply_with_tools()` 也同步接收多轮 messages。
- `build_dialogue_prompt_parts()` 里的 `recent_text` 段落已经移除，避免和多轮 messages 重复注入上下文。

#### 8. 记忆检索感知会话方向

- `retrieve_memories_for_turn()` 和 `retrieve_memories_for_turn_async()` 支持 `session_digest`。
- `_query_for_retrieval()` 只抽取 `key_themes`、`emotional_arc`、`unresolved_threads`、`significant_changes`、`summary_200chars` 等稳定字段，不直接拼整段 JSON。
- `session_summary` 类型记忆在带有主题线索的查询里获得额外偏置，避免模糊输入只命中字面更近但方向更弱的记忆。

#### 9. 隐私清理同步

- `privacy_service` 的 chat 导出包含 `session_digest`。
- 删除聊天时会同时清空 `last_summary` 和 `session_digest`。

### 相关文档

- `docs/context-continuity-design.md`

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_tooling.py tests/test_tooling_integration.py -q
```

结果：`105 passed, 2 warnings`。

warnings 仍来自 LangGraph / LangChain 的既有提示，以及 `tests/test_privacy.py` 里对 SQLAlchemy model 类名的既有 pytest 收集提示。

## 2026-05-13

### LLM 更新 `session_digest`

在上一轮已经打通 `session_digest` 的字段、运行时透传、持久化和检索读取之后，本轮补上真正的会话全景更新能力。

### 已完成改动

#### 1. 新增会话全景更新服务

- 新增 `session_digest_service`，统一负责构造 LLM 更新提示词、解析 JSON、做 schema 归一化和长度限制。
- 固定输出 `schema_version`、`key_themes`、`emotional_arc`、`effective_interventions`、`ineffective_interventions`、`unresolved_threads`、`significant_changes`、`last_updated_turn`、`summary_200chars`。
- 对列表字段做最多 5 项限制，`summary_200chars` 控制在 200 字以内。

#### 2. 隐私与高风险保护

- 对邮箱、长数字联系方式等明显个人标识做过滤。
- 当风险等级为 `L2/L3` 时，提示词要求只保留概括性安全连续性信息，不记录具体工具、地点、方法等可操作风险细节。
- 服务端也会对常见高风险细节词做二次概括过滤。

#### 3. 接入 `summarize_turn`

- `summarize_turn` 现在会调用 LLM 合并旧 `session_digest` 与本轮信息。
- LLM 返回合法 JSON 时，返回新的 `session_digest`，并优先用 `summary_200chars` 作为 `session_summary`。
- LLM 不可用、超时、空响应或 JSON 无效时，保留旧 `session_digest`，并继续使用原有模板摘要作为回退。
- `failed_no_reply` 不触发 LLM 更新，也不会覆盖旧 digest。

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py -q
```

结果：`9 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。

补充运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_tooling.py tests/test_tooling_integration.py -q
```

结果：`109 passed, 2 warnings`。

warnings 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示，以及 `tests/test_privacy.py` 中 SQLAlchemy `TestHistory` 类名触发的既有 pytest 收集提示。

### `session_digest` 注入回复提示词

在 `session_digest` 已经可持续更新、检索也已读取 digest 后，本轮把会话全景正式注入回复提示词，让 LLM 回复时直接知道当前对话在延续什么。

### 已完成改动

#### 1. 新增紧凑会话全景块

- `dialogue_prompt_builder` 会从 `session_digest` 中抽取稳定字段，生成“会话全景”提示块。
- 注入字段包括 `summary_200chars`、`key_themes`、`emotional_arc`、`effective_interventions`、`ineffective_interventions`、`unresolved_threads`、`significant_changes`。
- 空字段不会进入 prompt，避免噪音。

#### 2. 避免暴露调试字段和原始 JSON

- prompt 不直接 dump 整段 `session_digest`。
- `schema_version`、`last_updated_turn` 等内部字段不会暴露给 LLM。
- 每个字段会做紧凑截断，避免会话全景块膨胀。

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_dialogue_prompt_builder.py -q
```

结果：`2 passed`。

### 基于会话全景提取记忆候选

在回复提示词已经能读取 `session_digest` 之后，本轮把记忆候选提取也接上会话全景，避免长期记忆只盯着单轮文本。

### 已完成改动

#### 1. 会话全景驱动长期记忆候选

- `memory_candidate_extract` 在 `long_term` 模式下，会同时读取 `session_digest`。
- 从 `summary_200chars`、`key_themes`、`emotional_arc`、`effective_interventions`、`unresolved_threads`、`significant_changes` 里抽取候选线索。
- 这样即使当前轮文本很短或很模糊，也能保留会话级稳定主题和未展开线索。

#### 2. 保持短摘要模式不膨胀

- `summary_only` 仍然只保留 `session_summary`。
- `skip_sensitive`、`failed_no_reply`、`memory_mode=off` 这些既有门禁继续优先。

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py -q
```

结果：`13 passed, 1 warning`。

### 多轮上下文动态预算裁剪

在 `session_digest` 已经能够持续更新后，本轮继续优化回复链路里的多轮上下文窗口，避免固定条数带来的两类问题：短消息时上下文不够、长消息时 prompt 过长。

### 已完成改动

#### 1. 扩大候选历史窗口

- `chat_service` 给图运行时提供的 `recent_messages` 候选从最近 8 条扩大到最近 24 条。
- 候选扩大只影响进入图的上下文材料，不改变数据库消息存储和排序逻辑。

#### 2. LLM 输入前按预算裁剪

- `response_nodes` 在构造主回复和工具回复 messages 前，会先过滤最近对话。
- 过滤规则从最新消息往前选，保留更近的上下文，旧消息超预算会被舍弃。
- 单条历史消息会先做长度裁剪，历史消息总量控制在 1800 字符以内。
- 如果 `recent_messages` 最后一条就是当前用户输入，会继续去重，避免当前轮重复注入。

#### 3. 主回复和工具回复共用裁剪结果

- 主回复分支和工具分支都仍然通过同一套 `_reply_messages()` 构造 messages。
- 因此预算裁剪会同时作用于普通回复和带工具回复。

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py tests/test_chat_idempotency.py -q
```

结果：`20 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。

补充运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_tooling.py tests/test_tooling_integration.py -q
```

结果：`112 passed, 2 warnings`。

warnings 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示，以及 `tests/test_privacy.py` 中 SQLAlchemy `TestHistory` 类名触发的既有 pytest 收集提示。
