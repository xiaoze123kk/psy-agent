# summarize_session Tool 设计

## 动机

当前 `save_memory_summary` 工具面向后台记忆管道——LLM 生成的摘要和记忆候选直接流入 `memory_patch → memory_job → UserMemory`，用户不可见。但心理咨询场景中，来访者常有"帮我总结一下今天我们聊了什么""我们刚才讨论了哪些问题？"这类需求。缺少一个**面向用户端**的会话总结工具。

`summarize_session` 填补这个空白：它从对话状态中提取已经发生的内容，以结构化形式返回给 LLM，由 LLM 组织成自然语言呈现给用户。**不做新的 LLM 调用，不写数据库，纯读操作。**

## 设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 数据来源 | AgentState 内已有字段（`recent_messages`, `last_summary`, `session_summary`）+ handler 内逻辑拼接 | 零外部依赖，不增加 API 调用 |
| LLM 调用 | 无 | 工具只做数据提取和结构化，由对话 LLM 自行组织语言回复用户 |
| 写入 | 无 | 纯读操作，不产生副作用 |
| 风险等级 | L0-L3（全部） | 只读已有对话内容，无安全风险 |
| 是否需要 memory_mode | 否 | 即使 memory off 也能用 |
| 是否需要 knowledge_enabled | 否 | 与知识库无关 |
| 格式控制 | 参数 `format` 控制输出详细程度 | 不同场景需要不同粒度 |

## 参数设计

```json
{
  "type": "object",
  "properties": {
    "format": {
      "type": "string",
      "enum": ["brief", "detailed", "themes_only", "progress"],
      "description": "brief: 一段话概述本轮会话; detailed: 含主题/情绪/进展的完整总结; themes_only: 仅列出讨论过的核心主题; progress: 对比之前轮次看进展变化"
    }
  },
  "additionalProperties": false
}
```

### format 语义

| format | 返回内容 | 适用场景 |
|--------|---------|---------|
| `brief` (默认) | 1-2 句会话概述 + 本轮话题 | 用户随口问"聊了什么" |
| `detailed` | 会话概述 + 主题列表 + 情绪变化 + LLM 已给出的策略/建议摘要 | 用户认真想做回顾 |
| `themes_only` | 仅核心主题关键词列表 | 用户想快速了解覆盖了哪些话题 |
| `progress` | 较前几轮的对比变化：新主题、未解决线索、情绪走向 | 用户关心"有没有进展" |

## 数据来源

工具 handler 从 `state` 中提取以下字段进行组装：

| 数据 | state 字段 | 说明 |
|------|-----------|------|
| 对话历史 | `recent_messages` | 最近 N 条消息（user + assistant），用于提取本轮话题和 LLM 建议 |
| 上一轮摘要 | `last_summary` | 上一轮结束后生成的模板摘要 |
| 本工具产出 | `session_summary` | LLM 通过 `save_memory_summary` 生成的本轮摘要（如存在） |
| 意图 | `intent` | 本轮对话意图分类 |
| 情绪标注 | 从 `recent_messages` 的 assistant 回复中提取（如有情绪相关表述） | 不做 NLP，只做关键词匹配 |

## Handler 逻辑

```
summarize_session(arguments):
  format = arguments.format or "brief"
  recent = state.recent_messages (最近 12 条)
  
  // 提取用户消息
  user_messages = [m for m in recent if m.role == "user"]
  
  // 提取 assistant 回复
  assistant_messages = [m for m in recent if m.role == "assistant"]
  
  // 提取话题关键词（基于用户消息的简单分词 + 频率）
  topics = extract_topics(user_messages)
  
  // 按 format 组装
  switch format:
    "brief":
      return { overview, current_topic, turn_count }
    "detailed":
      return { overview, topics, theme_list, suggestions_summary, turn_count }
    "themes_only":
      return { themes }
    "progress":
      return { topics, topic_changes, ongoing_themes, turn_count }
```

### 话题提取策略

不做 NLP/LLM。基于现有 `last_summary` 和 `session_summary` 中的关键词 + 用户消息中出现频率较高的实词（去停用词后 2-4 字词组）。精度不求完美——LLM 拿到结构化数据后自己会用自然语言组织。

### 建议/策略提取

从 assistant 回复中提取"你可以试试""建议你""不妨"等引导词后的内容片段。同样交给 LLM 自己判断如何呈现。

## 返回数据结构

```json
{
  "format": "detailed",
  "overview": "本次会话共 N 轮对话，主要围绕职场压力和亲子关系展开",
  "topics": ["职场倦怠", "与领导的沟通困难", "睡眠质量下降"],
  "theme_count": 3,
  "turn_count": 8,
  "current_turn_topic": "用户表达了换工作的想法",
  "suggestions_given": ["尝试记录情绪日志", "每天散步10分钟"],
  "mood_indicators": ["焦虑", "疲惫", "在对话后半段有所缓解"],
  "source": "conversation_state"
}
```

### 字段说明

| 字段 | 类型 | 始终返回 | 说明 |
|------|------|---------|------|
| `format` | string | 是 | 实际使用的格式 |
| `overview` | string | brief/detailed | 会话整体概述 |
| `topics` | list[string] | 除 themes_only 外 | 讨论过的核心话题 |
| `theme_count` | int | brief/detailed | 话题计数 |
| `turn_count` | int | 是 | 本轮已发生的对话轮次 |
| `current_turn_topic` | string | brief/detailed | 本轮当前讨论的话题 |
| `suggestions_given` | list[string] | detailed | LLM 已给出的建议/策略 |
| `mood_indicators` | list[string] | detailed | 从对话中推断的情绪标注 |
| `source` | string | 是 | 固定 "conversation_state"，区分未来可能的 DB 来源 |

## 工具注册

```python
ToolSpec(
    name="summarize_session",
    description="Summarize the current conversation session for the user. "
                "Returns an overview, key topics, mood indicators, and suggestions "
                "that have already been discussed. Read-only, no side effects.",
    allowed_risk_levels=ALL_RISK_LEVELS,
    parameters={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["brief", "detailed", "themes_only", "progress"],
                "description": "brief: short overview; detailed: full summary with themes/mood/suggestions; "
                               "themes_only: core themes only; progress: changes compared to earlier turns.",
            },
        },
        "additionalProperties": False,
    },
)
```

## ToolGate 权限

| 条件 | 是否可用 |
|------|---------|
| L0-L1 + memory on/off | 是 |
| L2-L3 (高风险) | 是 |
| knowledge on/off | 是 |
| 所有模式 | 是 |

唯一无条件全场景可用的工具之一（与 `get_current_time` 同级）。

## LLM 使用模式

```
# 用户: "帮我总结一下今天聊了什么"
LLM 调用 summarize_session:
  format: "detailed"

# 工具返回结构化数据 → LLM 组织成自然语言:
"好的，我来帮你回顾一下。今天我们已经聊了 8 轮，主要围绕三个主题：
1. 职场倦怠——你提到最近对工作提不起兴趣
2. 与领导的沟通——你觉得自己的想法不被重视
3. 睡眠——最近入睡困难

在这个过程中，我们讨论过尝试记录情绪日志和每天散步。你现在感觉怎么样，还有什么想深入聊的吗？"
```

## 不动什么

- 不新增 LLM 调用
- 不修改 `save_memory_summary`
- 不依赖 `session_digest`（该特性还在设计中）
- 不写数据库
- 不动前端

## 改动范围

| 文件 | 改动 |
|------|------|
| `app/services/tooling.py` | TOOL_SPECS 新增 `summarize_session`；新增 `_build_summarize_session_handler`；ToolGate 无须改动（ALL_RISK_LEVELS 自动放行）；`_tool_prompt_hint` 新增描述 |
| `tests/test_tooling.py` | 新增测试：4 种 format 返回结构验证、空 recent_messages、缺少 session_summary 降级 |

## 与现有工具的关系

```
用户问"总结一下"
  → LLM 判断: 这不是写记忆，是读对话
  → 调 summarize_session (读 state)
  → 不调 save_memory_summary (那是写操作，语义不同)

save_memory_summary: 每轮自动调，写后台记忆
summarize_session: 用户主动请求时才调，读对话状态
```

## 未来迭代方向

- `session_digest` 落地后，`summarize_session` 可从 digest 中获取更精准的 `emotional_arc`、`key_themes`、`unresolved_threads`
- 可新增 `format: "homework"` 输出 CBT 作业模板（与 `cbt_homework` 工具互补）
- 可新增 `format: "export"` 输出适合复制保存的纯文本总结
