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

### 跳过轻量轮次的摘要更新

为了降低会话摘要更新的尾部延迟，本轮给 `session_digest` 更新加了一个轻量跳过条件。

### 已完成改动

#### 1. 轻量轮次直接回退

- 当已有旧 `session_digest`，且当前轮只有超短确认词或近乎空内容时，`update_session_digest_with_llm` 会直接跳过 LLM。
- 这样可以避免对没有新增信息的回合做无意义的模型调用。

#### 2. 保持高风险回合和实质变化回合继续更新

- `L2/L3` 风险回合不会被这个短路影响。
- 只要当前轮有实质内容，仍然会照常更新 digest。

### 验证结果

运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_response_memory_continuity.py -q
```

结果：`14 passed, 1 warning`。

补充运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_tooling.py tests/test_tooling_integration.py tests/test_dialogue_prompt_builder.py -q
```

结果：`117 passed, 2 warnings`。

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

### 长期用户画像透传到回复提示词

为了让回复模型不只理解“这一轮说了什么”，还理解“这个用户稳定偏好是什么”，本轮新增轻量用户画像汇总。

### 已完成改动

#### 1. 新增用户上下文汇总服务

- 新增 `user_context_service.build_user_profile_digest()`，从 `UserProfile`、`UserSettings` 和长期 `UserMemory` 中汇总稳定画像。
- 输出字段包括昵称、年龄段、用户模式、使用目标、互动偏好、稳定画像线索、偏好线索和纠错线索。
- 列表字段会去重、限量和截断，避免把原始数据库行或过长内容直接塞进 prompt。

#### 2. 图运行时透传

- `chat_service` 在准备一轮对话时构造 `user_profile_digest`。
- `GraphRuntime`、`AgentState` 和 `load_user_profile` 都透传该字段。
- 普通回复和流式回复路径都使用同一份用户画像上下文。

#### 3. 回复提示词注入

- `dialogue_prompt_builder` 新增“用户画像”提示块。
- prompt 只展示稳定偏好和长期线索，不暴露 `schema_version` 等内部字段。
- 纠错偏好保留独立短项，为后续纠错记忆优化预留入口。

### 验证结果

先按 TDD 写入失败测试；压缩前首次运行时因为 `user_context_service` 尚未实现，测试收集失败，符合预期红灯。

补齐实现后运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_user_context_service.py tests/test_dialogue_prompt_builder.py tests/test_chat_idempotency.py -q
```

结果：`14 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。

### 纠错记忆写入与检索

为了让模型记住用户明确表达过的“不要这样回应”，本轮把纠错偏好从普通偏好里拆成独立记忆类型。

### 已完成改动

#### 1. 新增 `correction` 可见记忆类型

- `memory_service` 将 `correction` 加入可见记忆类型、标题标签和类型排序。
- `upsert_memory_candidates()` 在长期记忆模式下可直接写入 `correction` 候选，不再回退成 `session_summary`。
- 自动标签增加“纠错”，便于后续检索和审计。

#### 2. 明确负反馈候选提取

- `memory_candidate_extract` 识别“不要一上来”“别直接”“先听我”“别下结论”等明确纠错表达。
- 命中后生成高重要度 `correction` 候选，内容保留为概括性的陪伴方式纠正。
- 原有 `preference` 候选仍保留，兼容较宽泛的偏好表达。

#### 3. 检索优先级增强

- `retrieve_memories_for_turn()` 在查询含有“不要 / 别 / 先听 / 听我说”等信号时提高 `correction` 类型得分。
- 当用户再次表达同类风格反馈时，纠错记忆会比普通偏好或会话摘要更靠前。

### 验证结果

先写失败测试后运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_response_memory_continuity.py -q
```

红灯结果：`3 failed, 33 passed, 1 warning`，失败分别覆盖候选未生成、写入类型被归一化、检索未优先命中。

补齐实现后再次运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_response_memory_continuity.py -q
```

结果：`36 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。

### 目标状态与检索重排

为了让模型更清楚“用户现在想解决什么”，本轮新增轻量 `goal_state`，并让目标相关记忆在模糊接续输入中更靠前。

### 已完成改动

#### 1. 新增目标状态汇总

- `user_context_service.build_goal_state()` 会汇总当前显式目标、用户设置中的使用目标、长期 `goal` 记忆和会话全景中的未展开线索。
- `chat_service` 在每轮准备上下文时构造 `goal_state`。
- `GraphRuntime`、`AgentState` 和输入节点会透传 `goal_state`，普通回复与流式回复路径一致。

#### 2. 显式目标候选提取

- `memory_candidate_extract` 识别“我想 / 我希望 / 目标 / 计划 / 先把 / 理清楚 / 解决”等目标表达。
- 命中后生成 `goal` 候选，保留为概括性的当前目标记忆。
- `summary_only` 模式仍然只写会话摘要，不引入长期目标候选。

#### 3. 目标感知检索重排

- `retrieve_memories_for_turn()` 新增 `goal_state` 参数。
- 检索 query 会合并当前目标、使用目标、目标记忆和未展开线索。
- 当用户说“继续这个 / 接着刚才”这类模糊输入时，`goal`、`profile`、`correction`、`preference` 会获得目标上下文偏置，优先于普通 `session_summary`。

### 验证结果

先写失败测试后运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_memory.py tests/test_response_memory_continuity.py -q
```

红灯结果：`3 failed, 58 passed, 1 warning`，失败分别覆盖 `goal_state` 参数缺失、运行时未透传、目标候选未生成。

补齐实现后再次运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_memory.py tests/test_response_memory_continuity.py -q
```

结果：`61 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。

### 低置信度澄清路由

为了避免用户只说“继续 / 有点乱 / 说不清”时模型硬给一长串建议，本轮新增低置信度澄清分支。

### 已完成改动

#### 1. 控制面识别信息不足

- `control_plane` 在低风险普通支持场景中检查输入是否过短、过模糊，以及是否缺少 `last_summary`、`session_digest` 或 `goal_state` 可承接上下文。
- 命中后设置 `clarification_needed` 和 `clarification_reason`。
- 澄清场景关闭 RAG，并把 response contract 收窄为 `one_clarifying_question`。

#### 2. 独立澄清回复节点

- 新增 `clarification_response`，只返回一个关键问题，不调用 LLM 扩写。
- 如果已有当前目标，会围绕该目标追问最卡的一点；如果完全缺上下文，会先确认用户想从事件还是感受说起。
- 不返回建议动作，避免把澄清轮变成建议轮。

#### 3. 主图路由接入

- `route_by_control` 在安全、红旗和边界分支之后识别澄清分支。
- `main_graph` 新增 `clarification_response` 节点，并接入 validator、摘要和记忆候选后续链路。
- `dialogue_prompt_builder` 也补充澄清模式提示，防止未来复用 LLM 回复路径时退化。

### 验证结果

先写失败测试后运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q
```

红灯结果：`2 errors, 1 warning`，失败来自 `clarification_response` 尚未实现。

补齐实现后再次运行：

```powershell
& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q
```

结果：`14 passed, 1 warning`。

warning 仍来自 LangGraph / LangChain 的既有 pending deprecation 提示。
