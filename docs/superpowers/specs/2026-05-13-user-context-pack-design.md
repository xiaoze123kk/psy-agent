# 统一用户上下文打包器设计

## 背景

当前对话链路已经具备 `session_digest`、`user_profile_digest`、`goal_state`、澄清答案、纠错记忆和检索记忆等信号。但这些信号在 prompt 中分散出现，模型需要自己判断优先级，容易出现旧摘要、旧偏好或检索记忆盖过当前目标与最新纠错的情况。

## 目标

1. 新增一个轻量 `user_context_pack`，把“当前目标、会话焦点、用户画像、纠错偏好、未展开线索、检索记忆提示”统一打包。
2. 明确优先级：当前目标/澄清答案 > 纠错提示 > 会话焦点 > 稳定画像 > 检索记忆。
3. 回复 prompt 优先读取 `user_context_pack`，旧的 `session_digest` 和 `user_profile_digest` prompt 块作为兼容回退。
4. 不改数据库结构，不改变现有记忆写入和安全策略。

## 输出结构

`user_context_pack` 是一个 dict，字段固定为：

- `schema_version`
- `active_goal`
- `conversation_focus`
- `style_corrections`
- `profile_hints`
- `open_threads`
- `retrieved_memory_hints`
- `priority_notes`

所有文本字段都去重、截断、限量。高风险 `L2/L3` 场景只保留安全允许的概括性上下文，不注入普通用户画像和普通可见记忆。

## 数据流

1. `chat_service._prepare_turn_context()` 在检索记忆后调用 `build_user_context_pack()`。
2. `TurnContext` 保存 `user_context_pack`。
3. `GraphRuntime.invoke_turn()` 和 `stream_turn()` 接收并放入 `AgentState`。
4. `input_nodes.load_user_profile()` 保留已存在的 `user_context_pack`。
5. `dialogue_prompt_builder` 新增“用户上下文优先级包”块；如果 pack 存在，则不再重复注入旧的 `session_digest` 和 `user_profile_digest` 块。

## 测试策略

- `user_context_pack_service` 单元测试：合并目标、digest、画像、纠错提示和检索记忆，并按优先级截断。
- prompt 测试：pack 存在时 prompt 出现“用户上下文优先级包”，且不重复出现旧“会话全景/用户画像”块。
- chat 集成测试：`process_message_turn()` 会把 pack 传入 fake runtime。
- graph runtime 测试：`_build_input_state()` 保留 `user_context_pack`。
- 回归：跑用户上下文、prompt、记忆、连续性、幂等、澄清相关集合。
