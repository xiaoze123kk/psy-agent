# 上下文连续性优化方案

## 1. 现状判断

### 1.1 当前链路确实在“压缩上下文”

现在的回复链路里，LLM 主要拿到的是 `system + user` 两条消息。历史对话被压成 `recent_text`，再把上一轮摘要塞进 `last_summary`。这能工作，但它不是完整对话，只是对话残片。

同时，记忆检索仍然依赖 `last_summary + recent_messages` 的拼接文本，记忆候选提取也还是基于单轮 `normalized_text` 做规则匹配。于是信息在几个节点之间不断变短、变硬、变单薄。

### 1.2 主要问题

- `summarize_turn` 现在更像模板化短摘要，不会累积，也不会保留脉络。
- `_model_reply_state_update` 和 `_model_reply_with_actions` 还不是标准多轮消息输入。
- `run_dialogue_reply_with_tools` 也还是 `system + user`，工具分支没有同步升级。
- `_query_for_retrieval` 只拿到了局部上下文，检索很难知道“这轮到底在延续什么主题”。
- `memory_candidate_extract` 只看单条消息，判断不了位置、转折和重要性。
- `last_summary` 目前还有多个下游读取方，不能粗暴替换掉。

---

## 2. 优化目标

- 让对话连续性变成一等公民，而不是事后压缩结果。
- 不动安全路由、危机回复和 `response_validator` 的硬边界。
- 不显著增加用户感知延迟。
- 保留旧字段和旧读取方的兼容期。

---

## 3. 推荐方案

### 3.1 分阶段推进

不要一次性把所有节点都改掉。建议按下面顺序做：

1. 新增会话级 `session_digest`。
2. 把回复链路切到多轮 messages。
3. 把检索输入切到结构化会话信息。
4. 再考虑记忆候选提取升级。

### 3.2 `session_digest` 作为会话全景

建议在 `conversation_threads` 上新增一个 JSON/JSONB 字段 `session_digest`。它不是原始转写，而是持续更新的会话全景。

`last_summary` 继续保留，作为兼容短摘要或展示摘要使用；`session_digest` 才是连续性主载体。

建议字段：

| 字段 | 作用 | 说明 |
|------|------|------|
| `emotional_arc` | 情绪走向 | 例如“焦虑 -> 释放 -> 疲惫 -> 平静” |
| `key_themes` | 核心主题 | 最多保留 5 个稳定主题 |
| `effective_interventions` | 有效回应方式 | 哪些回应在这段会话里更有效 |
| `ineffective_interventions` | 无效回应方式 | 哪些说法会被回避或拒绝 |
| `unresolved_threads` | 未展开线索 | 提到但还没深入的话题 |
| `significant_changes` | 关键转折 | 新出现的重要信息或状态变化 |
| `last_updated_turn` | 最后更新轮次 | 方便回退和调试 |
| `summary_200chars` | 轻量摘要 | 给其他模块快速读取用 |

更新建议：

- 在 `response_validator` 之后异步更新，避免影响用户首包。
- 允许超时回退到旧值。
- 失败时只保留旧 digest，不阻塞主流程。
- 更新时优先保留稳定主题和转折，不要把整段内容原样塞进去。

### 3.3 回复链路改成多轮 messages

`_model_reply_state_update` 和 `_model_reply_with_actions` 应该改成标准多轮消息输入，而不是只靠 `system_prompt + user_prompt` 拼文本。

推荐结构：

```text
[system]    系统提示词 + session_digest
[assistant] 最近若干轮助手回复
[user]      最近若干轮用户消息
...
[user]      当前轮用户消息
```

建议保留最近 8 到 12 条消息作为输入窗口，具体数量按实际 token 长度调。

同步建议：

- `build_dialogue_prompt_parts` 中的 `recent_text` 只作为过渡兼容，稳定后再去掉。
- 主回复分支和工具分支都要同步切换，不要只改其中一条路径。
- 工具分支里的 `run_dialogue_reply_with_tools` 也应支持多轮 messages，否则上下文会在工具场景里断掉。

### 3.4 检索要感知会话方向

`_query_for_retrieval` 不要只看 `last_summary`。更合适的做法是把当前轮文本和 `session_digest` 的结构化字段一起拼进查询：

- `key_themes`
- `emotional_arc`
- `unresolved_threads`
- 必要时再加少量 `recent_messages`

这样检索就能知道“这轮是在继续职场压力、关系冲突，还是在收拢上一次的情绪波动”，而不是只匹配当前一句话。

这一步不需要改索引结构，也不需要重写检索算法，只是给检索更多、更稳定的上下文。

### 3.5 记忆候选提取先保守，后升级

短期内保留现在的关键词规则和安全过滤即可。更大的升级放到后续异步 worker 里做：让 `memory_job` 基于 `session_digest` 提取候选，而不是只看单条 `normalized_text`。

这样做的好处是：

- 不增加主回复延迟。
- 能看到整段会话的上下文。
- 更容易判断什么是真正值得写入的长期记忆。

---

## 4. 不改什么

以下模块建议保持不动：

- 风险检测和控制平面。
- `crisis / boundary / clinical_red_flag` 的硬编码安全回复。
- `response_validator` 作为最后安全网的职责。
- 长期记忆系统本身的存储职责。
- 异步写入和 consolidation 的整体机制。
- Tool 系统的职责边界。

这里只改“信息怎么在会话里流动”，不改“安全怎么兜底”。

---

## 5. 风险与回退

| 风险 | 影响 | 回退 |
|------|------|------|
| `session_digest` 迁移没做好 | 会话全景缺失 | 继续读 `last_summary` |
| 多轮 messages 只改了主分支 | 工具场景上下文仍断 | 工具分支同步升级 |
| digest 更新超时或失败 | 会话全景滞后 | 保留旧 digest |
| JSON 结构不稳定 | 下游读取复杂 | 限定固定字段并做 schema 校验 |
| prompt 变长 | token 增加 | 控制最近消息窗口，摘要保持短小 |

---

## 6. 验收标准

- 主回复和工具回复都能看到连续对话上下文。
- `session_digest` 成为会话全景主载体，`last_summary` 只保留兼容短摘要。
- 检索对“继续上一轮主题”的表现明显更稳。
- 安全路径、validator 和危机回复不受影响。
- 用户可感知延迟没有明显上升。

