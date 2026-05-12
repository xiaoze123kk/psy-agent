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
