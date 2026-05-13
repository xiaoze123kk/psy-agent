# Tool 按意图绑定优化分析

## 1. 当前 Tool 加载现状

### 1.1 当前 Tool 概览

系统定义 7 个 ToolSpec（`app/services/tooling.py:206-360`），通过 `ToolGate` 按风险等级做访问控制：

| # | Tool 名称 | 风险等级 | 默认启用 | 外部依赖 |
|---|-----------|---------|---------|---------|
| 1 | `search_memories` | L0, L1 | 是 | 无（state 内纯文本搜索） |
| 2 | `save_memory_summary` | L0, L1 | 是 | 无（写 state memory_patch） |
| 3 | `get_safety_resources` | 全部 | 是 | 无（纯内存数据） |
| 4 | `web_search` | L0, L1 | 是 | DuckDuckGo 搜索 |
| 5 | `get_current_time` | 全部 | 是 | 无（stdlib datetime） |
| 6 | `get_weather` | L0, L1 | 是 | wttr.in (httpx) |
| 7 | `ask_knowledge` | L0, L1 | **否** | 占位符，不启用 |

### 1.2 当前绑定机制

绑定发生在 `_model_reply_state_update()`（`response_nodes.py:163-191`）：

```python
tool_plan = dialogue_tooling.build_dialogue_tool_plan(state)
if tool_plan.tools:
    result = await dialogue_tooling.run_dialogue_reply_with_tools(
        state,
        system_prompt=prompt_parts.system_prompt,
        user_prompt=prompt_parts.user_prompt,
        tool_plan=tool_plan,
    )
```

**关键问题：** 不管这条消息是否需要 tool，只要 `tooling_enabled=True`（始终为真），**该风险等级允许的所有 tool schema 都绑进 API 请求**。低风险时每次请求绑 6 个 tool。

### 1.3 当前加载时机的三层设计

| 层级 | 内容 | 加载时机 | 开销评估 |
|------|------|---------|---------|
| ToolSpec 定义 | 7 个纯 Python dataclass | 模块 `import tooling` 时 | 几乎为零 |
| ToolGate 筛选 | 按 risk_level 过滤允许的 tool | 每次请求 `build_dialogue_tool_plan()` | 轻量 |
| Handler 闭包构造 | Python 闭包函数 | 同上 | 轻量 |
| 实际依赖（DuckDuckGo、httpx） | `web_search`、`get_weather` 的 import | handler 被执行时 | 按需 |

**结论：** Python 侧的加载时机已经做得不错了。真正的**浪费在于 LLM 侧**。

---

## 2. 问题诊断

### 2.1 LLM 侧的浪费

每次 API 请求都会在 `tools` 参数中传输全部 6 个 tool 的 JSON Schema，每个约 300-500 字节的 function description。总开销：

- **网络传输**：每条约 2KB 的额外 JSON
- **LLM 推理负担**：DeepSeek 需要在每次推理时理解 6 个 function description，判断要不要调 tool、调哪个
- **tool_choice="auto"** 意味着 LLM 需要在 assistant message 中做一次额外的"要不要调 tool"的决策

对于一条简单的"嗯好的，谢谢"这种无需任何 tool 的短消息，6 个 tool schema 是纯浪费。

### 2.2 当前 ToolGate 只有粗粒度控制

`ToolGate.allows()` 的过滤维度只有两个：

- **risk_level**：高风险 → 只保留 `get_safety_resources` + `get_current_time`
- **memory_mode**：`off` 时移除记忆类 tool

缺少**语义维度的过滤**——没有利用 `state` 中已有的 `intent`（意图分类结果）。

### 2.3 缺少"实际调用频率"的在线统计

当前没有记录每个 tool 被 LLM 实际调用的频率。如果某个 tool 99% 的情况下都不会被调，却每次都在 schema 里绑着，这本身就是浪费。

---

## 3. 改进方案

### 方案 A：意图驱动的 Tool 瘦身（推荐）

在每个 response 节点调用 `_model_reply_state_update()` 时，`state` 中已有 `intent` 字段（来自 `intent_classifier` 节点的分类结果）。根据 intent 只绑定相关的 1-3 个 tool：

| Intent | 绑定 Tool | 理由 |
|--------|----------|------|
| `vent`（倾诉） | `save_memory_summary` + `get_current_time` | 用户主要在表达情绪，需要记忆但不需搜索 |
| `question`（提问） | `web_search` + `search_memories` | 用户可能在找信息 |
| `greeting`（寒暄） | `get_current_time` + `get_weather` | 闲聊开场，可能问时间/天气 |
| `other`（其他） | 全部 6 个 | 意图不明确时保持兼容 |
| `boundary`（边界） | 无 | boundary 回复是硬编码的，不走 tool |
| `crisis`（危机） | `get_safety_resources` + `get_current_time` | 已是现有逻辑 |

**实现方式**：在 `build_dialogue_tool_plan()` 中增加一个 `intent` 参数，在 `ToolGate` 中增加 intent → tool_name 的映射。

```python
# tooling.py 中新增
_INTENT_TOOL_MAP: dict[str, frozenset[str]] = {
    "vent": frozenset({"save_memory_summary", "get_current_time"}),
    "question": frozenset({"web_search", "search_memories"}),
    "greeting": frozenset({"get_current_time", "get_weather"}),
    "other": frozenset(),  # 空表示全部开放
    "mood_check": frozenset({"save_memory_summary", "search_memories", "get_weather"}),
}

def build_dialogue_tool_plan(state, **kwargs):
    # ... 现有 gate 逻辑 ...
    intent = str(state.get("intent") or "other")
    # 用 intent 额外过滤
    intent_tools = _INTENT_TOOL_MAP.get(intent)
    if intent_tools:  # 非空则在 gate 基础上再瘦身
        plan.tools = [t for t in plan.tools 
                      if t["function"]["name"] in intent_tools]
```

**优势**：
- 改动量小（约 30 行）
- 不增加 API 调用次数
- 减少 50-80% 的 tool schema 体积
- 降低 LLM 错误调用 tool 的概率

**风险**：
- 意图分类错误时可能绑错 tool —— 用 `"other"` fallback 绑定全部 tool 兜底
- 需要和 `intent_classifier` 的输出保证一致性

### 方案 B：两阶段调用（不推荐）

先发 `tool_choice="none"` 的消息，若 LLM 回复中包含"我想查一下"之类的线索，再补带 tool 的第二轮。

**劣势**：
- 每次多一轮 API 调用，延迟增加 1-3 秒
- "需要 tool"的判断逻辑复杂且容易出错
- 用户体验显著下降

### 方案 C：简单瘦身——默认不绑记忆类 tool

去掉 `search_memories` 和 `save_memory_summary` 从默认 tool 列表中，只在用户显式表示"帮我记住""之前聊过什么"时才绑。

**优势**：更简单

**劣势**：太粗粒度，LLM 可能错失需要记忆的时机

---

## 4. 推荐

**方案 A（意图驱动瘦身）**，原因：

1. `intent` 字段已存在于 state 中，不需要改动上游节点
2. 改动范围小（仅 `tooling.py` 一个文件）
3. way more 精准——不同意图只暴露真正需要的 tool
4. 有 `"other"` 兜底保证兼容性
5. 不会增加 API 调用次数和延迟

---

## 5. 收益预估

| 维度 | 当前 | 优化后 |
|------|------|--------|
| 每次请求平均 tool 数量 | 6 个 | 1-3 个 |
| tool schema JSON 体积 | ~2KB | ~0.5KB |
| LLM tool_choice 决策空间 | 6 个 function | 1-3 个 function |
| 误调 tool 概率 | 中等 | 低 |
| 兼容性风险 | — | 低（`"other"` 保底） |
