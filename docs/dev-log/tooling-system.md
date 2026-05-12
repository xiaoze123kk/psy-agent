# 工具系统开发记录

## 工具总览

当前系统共有 **5 个 Tool**，全部基于 DeepSeek/OpenAI function-calling 协议，定义在 `backend/app/services/tooling.py`，由 LLM 在对话中自主调用。

| # | 工具名 | 用途 | 风险等级 | 需要知识库开关 | 状态 |
|---|--------|------|----------|---------------|------|
| 1 | `search_memories` | 搜索用户可见记忆索引，返回记忆引用（非原始内容） | L0-L1 | 否 | 正式 |
| 2 | `save_memory_summary` | 生成安全会话摘要和候选记忆，提交后台记忆管道 | L0-L1 | 否 | 正式 |
| 3 | `get_safety_resources` | 按地区和受众返回安全支持资源（热线等） | L0-L3 | 否 | 正式 |
| 4 | `web_search` | 搜索互联网获取实时心理支持资源、热线和专业信息 | L0-L1 | 否 | 正式 |
| 5 | `get_current_time` | 获取当前 UTC/本地时间、星期、时区、会话已持续时间 | L0-L3 | 否 | 正式 |
| - | `ask_knowledge` | 知识库查询（占位，v1 禁用） | L0-L1 | 是 | 禁用 |

### 工具门控规则

| 条件 | 可用工具 |
|------|----------|
| 低风险 (L0-L1) + memory on | `search_memories`, `save_memory_summary`, `get_safety_resources`, `web_search`, `get_current_time` |
| 低风险 (L0-L1) + memory off | `get_safety_resources`, `get_current_time` |
| 高风险 (L2-L3) | `get_safety_resources`, `get_current_time` |
| 知识库启用 + 低风险 | 以上 + `ask_knowledge` |

---

## web_search 工具

### 初次实现 (2026-05-11)

- **搜索后端**：DuckDuckGo（`duckduckgo_search` 库，MIT 协议，免费无需 API key）
- **调用方式**：Tool（LLM 自主判断何时搜索）
- **region**：固定 `cn`（中国大陆）
- **核心文件**：
  - `backend/app/services/search_service.py` — 搜索逻辑
  - `backend/app/services/tooling.py` — Tool 注册、handler、ToolGate
- **定位**：长期保留，未来与知识库互补（知识库做深度，搜索做广度）

### 迭代优化记录

| # | 优化项 | 日期 | 描述 |
|---|--------|------|------|
| 1 | PII 排除提示 | 2026-05-11 | system prompt 约束：不将用户个人信息拼入搜索 query |
| 2 | 清洗优化 | 2026-05-11 | 去除首尾省略号 (`...`)、解码 HTML 实体 (`&amp;` → `&`)、空白符规范化 |
| 3 | 去重优化 | 2026-05-11 | 两层去重：URL 精确匹配 + snippet 前 60 字符 5-gram 重叠率 ≥70% 判为重复 |
| 4 | 截断优化 | 2026-05-11 | 智能边界截断：优先在 CJK 标点（`。，、；：？！`）或空格处断开，不在字符中间切断 |
| 5 | 超时控制 | 2026-05-11 | `ThreadPoolExecutor` + `future.result(timeout=8s)`，防止慢响应阻塞对话轮次 |
| 6 | 权威评分 | 2026-05-12 | 域名分三级（gov/edu +100，baike/医院 +50，其余 0），HTTPS +5，路径浅层 +5，标题权威词 +10，结果按分降序 |
| 7 | 去重性能优化 | 2026-05-12 | 预计算 `_ngram_fingerprint`（key + 5-gram set），避免循环内重复正则和集合构建 |
| 8 | 低信息过滤 | 2026-05-12 | 丢弃 snippet < 12 字符或含 "点击查看"/"read more" 等无价值 boilerplate 的结果 |

#### 权威评分域名细则

**Tier 1 (+100)**：政府/机构/学术
- `gov.cn` 系列、`who.int`、`nih.gov`、`nhs.uk`、`cdc.gov`
- `edu.cn` 系列
- `psych.ac.cn`、`cma.org.cn`

**Tier 2 (+50)**：权威内容平台
- `baike.baidu.com`、`zh.wikipedia.org`
- `dxy.cn`（丁香园）、`medlive.cn`（医脉通）
- 含 `.hospital.`、`.med.`、`.psy.` 的域名

**额外加分**：HTTPS (+5)、URL 路径 ≤2 层 (+5)、标题含 "官方/热线/中心/医院/卫健委" 等 (+10)

| 9 | 错误状态传递 | 2026-05-12 | `search_web` 返回 `(results, error)` 元组；handler 在超时/网络异常时设 `status="error"`，LLM 可区分"无结果"与"搜索失败" |

---

## get_current_time 工具

### 实现 (2026-05-12)

- **返回内容**：`utc_iso`、`local_iso`（Asia/Shanghai）、`weekday`（中文）、`session_elapsed_seconds`
- **会话计时**：handler 闭包记录首次调用时间，后续调用返回增量
- **可用范围**：所有风险等级，包括 memory-off 和高风险场景

---

## 架构说明

```
tooling.py
├── TOOL_SPECS          → 5 个 ToolSpec 定义（tool 元数据 + 参数 schema）
├── ToolGate            → 按 risk_level / memory_mode / knowledge_enabled 控制可用性
├── DialogueToolPlan    → 一次性组装 tools + handlers + prompt_hint + audit
├── _build_*_handler    → 每个 tool 的 handler factory（闭包捕获 state / capture）
├── _tool_prompt_hint   → 注入 system prompt 的 tool 使用策略说明
└── run_dialogue_reply_with_tools → 对话入口，调用 deepseek_client.chat_with_tools()

search_service.py
├── SearchResult        → 数据类（title, url, snippet, score）
├── search_web()        → 搜索入口（DuckDuckGo → 清洗 → 去重 → 评分 → 排序）
├── _ddg_text()         → DDGS 封装（便于测试 mock）
├── 评分函数              → _score_domain / _score_https / _score_path_shallow / _score_title_authority
├── 清洗函数              → _strip_ellipsis / _unescape_html / _smart_truncate / _is_low_info
└── 去重函数              → _ngram_fingerprint / _fingerprints_match
```

## 测试覆盖

| 测试文件 | 测试数 | 覆盖内容 |
|----------|--------|----------|
| `tests/test_tooling.py` | 23 | ToolGate 规则、所有 handler 行为、audit capture、错误状态传递 |
| `tests/test_search_service.py` | 29 | 清洗、去重、截断、评分、低信息过滤、错误处理、超时、error tuple |
| `tests/test_tooling_integration.py` | 1 | 端到端 tool audit + memory patch 流转 |

**全量**：301 passed, 2 skipped, 0 failures
