# 用户理解优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型更稳定地记住“这个人是谁、在意什么、讨厌什么、现在想解决什么”，并在信息不足时先问一个关键问题。

**Architecture:** 复用现有 `UserProfile`、`UserSettings`、`ConversationThread.session_digest` 和 `UserMemory`，补一层轻量的用户上下文汇总，再把它透传到图状态、提示词、记忆检索和回复路由。长期画像、纠错记忆、目标状态、澄清路由四条链路分开实现，避免把所有信号塞进同一个摘要字段里。

**Tech Stack:** FastAPI, LangGraph, SQLAlchemy, DeepSeek, pytest

---

### Task 1: 长期用户画像透传到回复提示词

**Files:**
- Create: `backend/app/services/user_context_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/graph_runtime.py`
- Modify: `backend/app/graphs/nodes/input_nodes.py`
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_dialogue_prompt_builder.py`
- Test: `backend/tests/test_chat_idempotency.py`

- [ ] **Step 1: 写失败测试**

新增测试，确认 `user_profile_digest` 会进入图状态和回复 prompt，且只保留稳定字段，不暴露原始数据库行。

- [ ] **Step 2: 跑测试确认失败**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_dialogue_prompt_builder.py tests/test_chat_idempotency.py -q`

- [ ] **Step 3: 实现最小代码**

新增 `build_user_profile_digest()`，从 `UserProfile`、`UserSettings`、`usage_goals` 和已存在的长期偏好记忆中汇总出可透传的用户画像块；把它接入 `GraphRuntime._build_input_state()`、`chat_service._prepare_turn_context()`、`input_nodes.load_user_profile()` 和 `dialogue_prompt_builder.build_dialogue_prompt_parts()`。

- [ ] **Step 4: 跑测试确认通过**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_dialogue_prompt_builder.py tests/test_chat_idempotency.py -q`

- [ ] **Step 5: 中文前缀提交**

```bash
git add backend/app/services/user_context_service.py backend/app/services/chat_service.py backend/app/services/graph_runtime.py backend/app/graphs/nodes/input_nodes.py backend/app/services/dialogue_prompt_builder.py backend/tests/test_dialogue_prompt_builder.py backend/tests/test_chat_idempotency.py
git commit -m "feat: 注入长期用户画像"
```

### Task 2: 纠错记忆写入与检索

**Files:**
- Modify: `backend/app/services/memory_service.py`
- Modify: `backend/app/graphs/nodes/memory_nodes.py`
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_memory_service.py`
- Test: `backend/tests/test_response_memory_continuity.py`

- [ ] **Step 1: 写失败测试**

新增测试，确认明确的负反馈或偏好纠正会生成 `correction` 记忆候选，且检索时会优先命中这类“别这样说/先听我说”信号。

- [ ] **Step 2: 跑测试确认失败**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_response_memory_continuity.py -q`

- [ ] **Step 3: 实现最小代码**

把 `correction` 加进记忆类型白名单、标签和排序；在 `memory_candidate_extract()` 里把明确纠错句式写成 `correction` 候选；在 prompt 里把纠错偏好作为单独短块喂给模型。

- [ ] **Step 4: 跑测试确认通过**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_response_memory_continuity.py -q`

- [ ] **Step 5: 中文前缀提交**

```bash
git add backend/app/services/memory_service.py backend/app/graphs/nodes/memory_nodes.py backend/app/services/dialogue_prompt_builder.py backend/tests/test_memory_service.py backend/tests/test_response_memory_continuity.py
git commit -m "feat: 增强纠错记忆"
```

### Task 3: 目标状态与检索重排

**Files:**
- Modify: `backend/app/services/user_context_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/memory_service.py`
- Modify: `backend/app/graphs/nodes/memory_nodes.py`
- Test: `backend/tests/test_memory_service.py`
- Test: `backend/tests/test_memory.py`

- [ ] **Step 1: 写失败测试**

新增测试，确认显式目标和当前任务会形成 `goal_state`，并让 `goal` / `profile` / `correction` / `preference` 记忆在模糊查询里比普通会话摘要更靠前。

- [ ] **Step 2: 跑测试确认失败**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_memory.py -q`

- [ ] **Step 3: 实现最小代码**

补 `goal_state` 汇总与透传；在检索打分里增加目标相关性和用户画像相关性；让 `memory_candidate_extract()` 能写出 `goal` 候选，并保持旧的 summary-only 路径不变。

- [ ] **Step 4: 跑测试确认通过**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory_service.py tests/test_memory.py -q`

- [ ] **Step 5: 中文前缀提交**

```bash
git add backend/app/services/user_context_service.py backend/app/services/chat_service.py backend/app/services/memory_service.py backend/app/graphs/nodes/memory_nodes.py backend/tests/test_memory_service.py backend/tests/test_memory.py
git commit -m "feat: 增强目标状态检索"
```

### Task 4: 低置信度澄清路由

**Files:**
- Modify: `backend/app/graphs/state.py`
- Modify: `backend/app/graphs/nodes/control_nodes.py`
- Modify: `backend/app/graphs/nodes/response_nodes.py`
- Modify: `backend/app/graphs/routing.py`
- Modify: `backend/app/graphs/main_graph.py`
- Modify: `backend/app/services/dialogue_prompt_builder.py`
- Test: `backend/tests/test_conversation_control_rag.py`
- Test: `backend/tests/test_conversation_quality.py`

- [ ] **Step 1: 写失败测试**

新增测试，确认当输入信息太短、太模糊或和已知画像/目标明显缺口时，图会走澄清分支，并且输出只包含一个关键问题，不会顺手给一长串建议。

- [ ] **Step 2: 跑测试确认失败**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q`

- [ ] **Step 3: 实现最小代码**

给状态加 `clarification_needed` / `clarification_reason`，加一个澄清回复节点和路由分支，在 prompt 里明确“信息不足时先问一个关键问题”。

- [ ] **Step 4: 跑测试确认通过**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q`

- [ ] **Step 5: 中文前缀提交**

```bash
git add backend/app/graphs/state.py backend/app/graphs/nodes/control_nodes.py backend/app/graphs/nodes/response_nodes.py backend/app/graphs/routing.py backend/app/graphs/main_graph.py backend/app/services/dialogue_prompt_builder.py backend/tests/test_conversation_control_rag.py backend/tests/test_conversation_quality.py
git commit -m "feat: 增加低置信度澄清"
```

### Task 5: 迭代日志与回归

**Files:**
- Modify: `docs/dev-log/context-continuity-optimization.md`

- [ ] **Step 1: 更新迭代日志**

把本批四个步骤的实现策略、失败回退、测试命令和结果补进同一份迭代日志。

- [ ] **Step 2: 跑回归**

Run: `& 'E:\心理咨询agent\backend\.venv\Scripts\python.exe' -m pytest tests/test_memory.py tests/test_memory_service.py tests/test_privacy.py tests/test_chat_idempotency.py tests/test_response_memory_continuity.py tests/test_tooling.py tests/test_tooling_integration.py tests/test_conversation_control_rag.py tests/test_conversation_quality.py -q`

- [ ] **Step 3: 最终提交**

```bash
git add docs/dev-log/context-continuity-optimization.md
git commit -m "perf: 提升用户理解与澄清能力"
```
