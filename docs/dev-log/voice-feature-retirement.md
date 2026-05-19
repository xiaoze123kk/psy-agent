# 语音功能退役开发日志

## 2026-05-18 后端语音能力移除

### 背景/问题

- 当前产品重点回到文字对话、记忆、风控和 RAG 链路，语音会话入口与存储字段暂不再作为可用功能维护。
- 旧的语音接口、语音会话表、用户语音偏好字段和 `input_type=voice` 会增加跨层维护成本，也容易让前端或接口文档误以为语音能力仍可用。

### 关键改动

- 移除后端 `/voice` 路由、语音 endpoint、schema、service 和对应安全测试。
- 清理用户设置、隐私导出、鉴权/个人资料响应中的语音相关字段。
- 将运行时和测试路径统一到文字输入，保留对 `input_type=text/test/system` 的约束。
- 新增 `database/migrations/0015_remove_voice_feature.sql`，删除 `voice_sessions` 与语音设置列，并把历史 `input_type=voice` 消息回填为 `text`。
- 更新数据库 README、API/PRD/模块说明等资料，避免继续暴露退役语音能力。

### 验证结果

- `backend/.venv/Scripts/python.exe -m pytest tests/test_tooling_integration.py::ToolingIntegrationTests::test_process_message_turn_carries_tool_audit_and_memory_patch -q`：通过，`1 passed`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_privacy.py tests/test_chat_idempotency.py tests/test_companion_styles.py tests/test_memory.py tests/test_memory_service.py tests/test_safety_evaluation.py tests/test_tooling_integration.py tests/test_user_context_service.py -q`：通过，`191 passed, 1 warning, 22 subtests passed`。
- 已检查 `database/migrations/` 顺序，新增退役语音迁移编号为 `0015`，位于现有 `0014_conversation_session_digest.sql` 之后。

### 后续事项

- 若后续重新引入语音，应作为新的独立能力重新设计权限、隐私声明、存储策略和前端入口，而不是复用已退役接口。
