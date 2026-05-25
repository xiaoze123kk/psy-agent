# Prompt Builder 与回复契约

> 返回：[[00 后端项目亮点分模块索引]]
> 相关代码：`backend/app/services/dialogue_prompt_builder.py`、`backend/app/graphs/nodes/response_nodes.py`

## 它解决什么问题

模型回复质量很大程度取决于 prompt，但 prompt 不能散落在各个节点里。

## Prompt builder 组织的信息

- system prompt。
- user prompt。
- response contract。
- conversation move policy。
- risk response policy。
- retrieved memories。
- counseling examples。
- user context pack。
- recent messages。

## 回复契约

`response_contract` 来自 control plane 和风险策略，用于约束回复：

- 当前能不能做安全检查。
- 是否允许 RAG。
- 字数、问句、语气边界。
- 是否要避免诊断、建议、过度分析。
- 高风险场景下应该使用什么安全回应方式。

## 和对话走向策略的关系

`conversation_move_policy` 更关注“怎么接话”：

- 问题预算。
- 分析深度。
- 开头偏好。
- 结构变化。
- 是否回应用户锚点。

Prompt builder 把 response contract 和 conversation move policy 合并进最终 prompt，让模型同时遵守安全与体验要求。

## 为什么是亮点

它让回复生成节点不需要自己拼大量字符串，而是围绕统一 prompt parts 工作。这有利于之后调 prompt、做 A/B、加 trace。

## 开发边界

- 修改 prompt 字段时，要同步测试 `dialogue_prompt_builder`。
- 不要把内部策略名直接暴露给最终用户。
- RAG 示例只能作为参考，不能鼓励模型复制原文。

## 推荐验证

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_dialogue_prompt_builder.py tests/test_conversation_control_rag.py -q
```
