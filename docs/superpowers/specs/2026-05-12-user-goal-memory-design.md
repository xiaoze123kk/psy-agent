# User Goal Memory 设计

## 动机

CBT/焦点解决/动机式访谈策略经常引导用户设定小目标。需要一种方式让 LLM 在对话中自然地创建、更新和查询小目标，且与现有记忆系统兼容。

## 设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 数据模型 | 复用 `UserMemory` 表 | 新 `memory_type="goal"`，目标元数据存 `structured_value` JSON |
| 工具 | 无需新 tool | 复用 `save_memory_summary` 写入，`search_memories` 查询 |
| 生命周期 | LLM 自主管理 | 创建、更新状态、完成后标记，全通过 memory_candidates 管线 |

## 数据模型

在 `UserMemory` 中：

```
memory_type: "goal"
title:       目标简称，如 "每天散步"（≤120 字）
content:     目标完整描述，如 "每天下楼散步至少10分钟，从小区门口走到公园再返回"
summary:     content 的简短版本（≤260 字）
importance:  1-5（默认 3，重要目标可上调）
tags:        ["散步", "运动", "routine"]
structured_value: {
  "goal_status": "active" | "completed" | "abandoned",
  "completed_at": "2026-05-20T..." | null,
  "goal_category": "behavior" | "emotion" | "social" | "routine" | "other"
}
visibility:  "user_visible"
status:      "active"
```

## 改动范围

| 文件 | 改动 |
|------|------|
| `app/services/tooling.py` | `VISIBLE_MEMORY_TYPES` 加 `"goal"`；`save_memory_summary` 参数 enum 加 `"goal"` |
| `app/services/memory_service.py` | `VISIBLE_MEMORY_TYPES` 加 `"goal"`；`MEMORY_TYPE_LABELS` 加 `"goal": "小目标"`；`MEMORY_TYPE_ORDER` 加 `"goal"` |
| `app/services/tooling.py` | `_normalize_memory_candidate` 支持 `structured_value` 字段 |
| `tests/test_tooling.py` | memory handler 测试验证 goal 类型的 candidate 被正确处理 |
| `tests/test_memory_service.py` | 验证 goal 类型能被 upsert 和检索 |

## LLM 使用模式

```
# 创建目标
LLM 调用 save_memory_summary:
  memory_candidates: [{
    memory_type: "goal",
    content: "每天散步至少10分钟",
    importance: 4,
    tags: ["散步", "运动"],
    structured_value: {goal_status: "active", goal_category: "routine"}
  }]

# 更新目标状态
LLM 调用 save_memory_summary:
  memory_candidates: [{
    memory_type: "goal",
    content: "每天散步至少10分钟",
    importance: 4,
    structured_value: {goal_status: "completed", goal_category: "routine"}
  }]

# 查询目标
LLM 调用 search_memories:
  query: "用户的当前目标",
  memory_types: ["goal"]
```

## 与现有管线的关系

```
save_memory_summary handler
  → memory_candidates 包含 goal 类型
  → _normalize_memory_candidate 保留 structured_value
  → memory_patch 传给 chat_service
  → upsert_memory_candidates 写入 UserMemory
  → 后续 search_memories 可检索
```
