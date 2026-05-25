# 后端保守重构设计

## 背景

本次重构只面向后端代码组织，目标是降低大文件阅读和维护成本，不改变现有 API、数据库结构、LangGraph 节点行为、提示词策略、记忆策略或风控语义。仓库当前后端主要代码位于 `backend/app/`，目录约定要求路由在 `app/api/v1/endpoints/`，图与节点在 `app/graphs/`，运行封装在 `app/services/graph_runtime.py`，本设计沿用这些边界。

扫描后，高复杂度集中在以下文件：

- `backend/app/services/memory_service.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/conversation_move_policy.py`
- `backend/app/graphs/nodes/validator_nodes.py`
- `backend/app/graphs/nodes/risk_nodes.py`

其中 `memory_service.py`、`chat_service.py`、`conversation_move_policy.py`、`validator_nodes.py` 是第一轮整理对象。`risk_nodes.py` 暂不拆分，只在实施时保留为观察对象，避免同时触碰风控核心分类逻辑导致验证面过大。

## 目标

- 保留现有公开导入路径，例如 `app.services.memory_service`、`app.services.chat_service`、`app.services.conversation_move_policy`、`app.graphs.nodes.validator_nodes`。
- 将纯常量、纯辅助函数和内部流程片段搬到相邻私有模块，让入口文件更接近“编排层”。
- 不改变函数签名、返回字段、异常语义、日志语义和测试可 monkeypatch 的全局对象。
- 不移动数据库模型、API schema、迁移文件、前端文件、语料数据或构建产物。

## 非目标

- 不改业务功能、Prompt 文案、风险等级规则、RAG 检索策略或记忆写入策略。
- 不做跨层目录大搬迁，例如把 `services/` 改成多个子包。
- 不重排历史 SQL migration。
- 不清理 `.playwright-mcp/`、`backend/data/*.json`、日志、截图或其他用户已有未跟踪文件。

## 方案

采用“保留门面模块，拆内部 helper”的方式：

1. 原入口文件继续暴露当前被 API、图节点和测试使用的函数。
2. 新增私有 helper 模块时使用同目录命名，例如 `memory_scoring.py`、`chat_turns.py`、`conversation_policy_helpers.py`、`validator_experience.py`。
3. 原入口文件导入 helper，并在必要时保留兼容包装函数，保证现有测试中直接访问的少量私有函数仍可用。
4. 每次拆分只移动一组职责，并立即跑对应测试，降低回归定位成本。

## 模块边界

### memory_service

`memory_service.py` 保留对外能力：

- `build_memory_index`
- `retrieve_memories_for_turn`
- `retrieve_memories_for_turn_async`
- `upsert_memory_candidates`
- `index_memory_embeddings`
- `consolidate_user_memories`
- `maybe_auto_consolidate_user_memories`
- `record_memory_feedback`
- `count_memory_operations`
- `list_memory_operations`
- `remove_memory_vectors`

可拆出职责：

- 文本清洗、tokenize、相似度和冲突判断。
- 记忆类型规范化、标题、标签、可见性判断。
- 向量检索评分与 fallback 排序。

实施时需保留测试中 patch 的对象位置：`memory_service.embedding_client`、`memory_service.milvus_store`、`memory_service._content_similarity`、`memory_service.MemoryEmbedding`。

### chat_service

`chat_service.py` 保留对外能力：

- `get_thread_for_user`
- `list_threads_for_user`
- `list_messages_for_thread`
- `process_message_turn`
- `process_message_turn_stream`
- `create_or_get_risk_event`

可拆出职责：

- turn claim、replay、complete、fail 等幂等流程。
- graph 调用 fallback、delivery result 归一化。
- stream event 构造和心跳辅助。

实施时需保留测试中 patch 的对象位置：`chat_service.graph_runtime`、`chat_service.settings`。

### conversation_move_policy

`conversation_move_policy.py` 保留对外能力：

- `build_conversation_move_policy`
- `default_actions_for_conversation_move_policy`

可拆出职责：

- cultural anchor / person anchor 提取。
- recent adaptation state 计算。
- intent lanes、voice contract、reply structure 的纯规则。

因为测试只导入两个公开函数，优先将 helper 移出，不需要保留私有 helper 兼容入口，除非实施中发现其他模块直接引用。

### validator_nodes

`validator_nodes.py` 保留 LangGraph 节点能力：

- `response_validator`
- `validator_reasons`
- `experience_validator_reasons`
- `failed_no_reply_validation_result`
- `is_safety_delivery_path`

可拆出职责：

- experience validator 的常量和纯规则。
- cultural claim 检测规则。
- repair prompt focus block 构造。

实施时需保留测试中 patch 的对象位置：`app.graphs.nodes.validator_nodes.deepseek_client.chat`。因此 `deepseek_client` 仍留在 `validator_nodes.py`，或者保留同名导入供 patch 生效。

## 数据流

本次整理不改变运行时数据流：

1. API endpoint 仍调用 `chat_service`。
2. `chat_service` 仍准备 turn context、调用 `GraphRuntime`、持久化消息和 trace、触发记忆 job。
3. LangGraph 仍通过现有节点调用风险、控制、RAG、响应和 validator。
4. 记忆读取、写入、向量索引仍通过 `memory_service` 的原公开函数进入。
5. `conversation_move_policy` 仍由 control node 构造，并被 prompt builder、validator、trace summarizer 消费。

## 错误处理

- 原有 fallback 行为保持不变：graph timeout、graph exception、failed_no_reply、validator block 都应返回原字段结构。
- helper 模块只做纯逻辑或局部编排，不吞异常，不改变日志 logger 名称中用户可观察的部分。
- 涉及 monkeypatch 的全局变量不迁移，避免测试和调用方失效。

## 测试策略

第一轮每个拆分步骤后运行相关最小测试：

- `python -m pytest tests/test_memory_service.py -q`
- `python -m pytest tests/test_memory.py -q`
- `python -m pytest tests/test_chat_idempotency.py -q`
- `python -m pytest tests/test_conversation_move_policy.py -q`
- `python -m pytest tests/test_conversation_control_rag.py -q`

完成后运行较宽的后端验证：

- `python -m pytest tests/test_dialogue_prompt_builder.py tests/test_graph_runtime_streaming.py tests/test_response_memory_continuity.py -q`

如果本地依赖或数据库环境导致某些集成测试无法运行，记录失败原因，并至少完成纯单元测试与 import smoke：

- `python -m compileall app`

## 风险与约束

- 中文常量和 prompt 文案存在编码显示问题，实施中只移动原文本，不改写文本内容。
- 测试中存在对私有函数和模块全局对象的直接访问，拆分时要优先兼容这些访问点。
- 不一次性拆 `risk_nodes.py`，因为它是风控分类核心，且测试直接引用内部函数 `_assessment_from_parts`。

## 验收标准

- 后端公开 API 和公开函数导入路径不变。
- 相关测试通过，或明确记录因外部服务/数据库缺失导致的不可运行项。
- 入口文件行数下降，职责更清晰，但没有行为差异。
- `git diff` 中不包含前端、数据库迁移、数据文件、缓存、日志或用户未跟踪文件。
