# Web Search Tool 设计

## 动机

心理咨询 agent 目前缺少实时信息获取能力：
- **危机场景**：用户需要附近真实求助资源（热线、机构），电话和地址可能变化，离线数据库无法保证实时性
- **权威资料**：知识库功能延期，需要搜索作为补充，未来知识库上线后搜索继续保留（知识库做深度，搜索做广度）

## 设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 搜索后端 | DuckDuckGo（免费 API） | 零成本、无需注册、隐私友好 |
| 调用方式 | Tool（LLM 自主调用） | 与现有 tooling 一致，模型判断何时搜、搜什么 |
| 生命周期 | 长期保留 | 知识库上线后不下掉，两者互补 |
| 危机 vs 通用 | 统一为 `web_search` tool | 模型自行区分场景，不引入多个搜索 tool |

## 架构

```
tooling.py
├── TOOL_SPECS: 新增 web_search (ToolSpec)
├── ToolGate: 增加 knowledge_enabled 门控
├── _build_web_search_handler(): 新增 handler factory
└── build_dialogue_tool_plan(): 注册 handler

search_service.py (新建)
├── search_web(): 调用 DuckDuckGo，清洗结果
└── 返回标准化结果列表
```

### Tool 定义

```
web_search:
  name: web_search
  description: 搜索互联网获取实时信息，用于查找心理援助资源、热线电话、专业信息等
  allowed_risk_levels: LOW_RISK_LEVELS (L0, L1)
  enabled_by_default: true
  parameters:
    query: string (required) — 搜索关键词
    max_results: integer (1-5, default 3) — 返回结果数
```

### ToolGate 规则

- `risk_level` 在 L0/L1 时可用（和 `search_memories` 一致）
- `knowledge_enabled` 不强制要求（危机场景不需要知识库开关）
- L2/L3 时不可用（高风险管理仅开放 `get_safety_resources`）

## 数据流

```
User Message
  → DialogueToolPlan 构建（含 web_search tool def + handler）
  → deepseek_client.chat_with_tools()
  → LLM 决定调用 web_search
  → handler.search_web(arguments)
      → duckduckgo_search.ddg_text(query, region="cn", max_results)
      → 结果清洗（截断 title/body，去重）
      → 返回 {query, count, items: [{title, url, snippet}]}
  → 结果注入对话上下文
  → LLM 整合到最终回复
  → audit_capture 记录预览
```

## 安全约束

- 搜索结果不做持久化，用完即抛
- URL 返回前端但不鼓励用户直接点击（前端可用 `rel=nofollow` 或禁用链接）
- system prompt 约束：不把用户个人身份信息拼入搜索 query
- 结果经 `_safe_preview` 截断（title 80chars, snippet 280chars）
- 仅返回 title/url/snippet，不包含原始 HTML

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/services/tooling.py` | 新增 `web_search` ToolSpec + handler + ToolGate 集成 |
| `backend/app/services/search_service.py` | 新建，封装 DuckDuckGo 搜索逻辑 |
| `backend/requirements.txt` | 新增 `duckduckgo_search` 依赖 |
| `backend/tests/test_tooling.py` | 新增 web_search handler 测试 |

## 测试要点

- handler 正常返回搜索结果
- 空 query 返回空结果
- max_results 截断逻辑
- audit_capture 记录预览
- ToolGate 在高风险时阻止 web_search
