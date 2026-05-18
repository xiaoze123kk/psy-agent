# Sprint 2 计划文档

## 1. Sprint 核心目标

Sprint 2 的目标是把 Sprint 1 的“登录 + 文本陪伴 + 风险分流”闭环，扩展成一个可演示的“自助支持闭环”：

首页状态记录
→ 知识搜索 / 知识问答
→ 状态测试 / 16 型人格风格测试
→ 测试结果回流对话
→ 记忆中心可见、可改、可删
→ 情绪趋势可回看
→ 高风险场景仍然强制安全分流

一句话目标：

做出一个“能记录状态、能查心理知识、能完成基础测试、能把结果带回聊天、能管理记忆，并保持安全边界”的 Sprint 2 可用版本。

## 2. Sprint 1 当前基线

当前代码已经具备以下基础：

- 前端：Vue 3 + Vite + TypeScript，已有登录、注册、首页、对话、我的页和 Demo 模式页面壳。
- 后端：FastAPI，已有 `/health`、认证、验证码、refresh token、对话线程、消息、SSE 流式响应、记忆 CRUD、情绪记录、SOS 资源接口。
- Agent：LangGraph 已有输入标准化、用户画像加载、风险识别、意图识别、陪伴回复、安抚回复、轻咨询回复、危机回复、摘要和记忆候选节点。
- 数据：已有 users、profiles、settings、threads、messages、risk_events、mood_logs、user_memories、refresh_tokens。

Sprint 2 不重做 Sprint 1 主链路，只在其上补齐内容、自助、记忆和评测能力。

## 3. 技术栈冻结

- 前端：Vue 3 + Vite + TypeScript
- 后端：Python 3.10/3.11 + FastAPI
- Agent：LangGraph Python
- 数据库：PostgreSQL 为正式目标，本地开发允许 SQLite 兜底
- LLM：DeepSeek 配置可用时调用；未配置时必须有稳定 fallback
- 接口文档：继续维护 `资料/backend-openapi.yaml` 与 `资料/frontend-api.yaml`

## 4. Sprint 2 范围

### 4.1 P0 必做

1. 知识库 MVP
   - 支持知识文章种子数据，首批不少于 20 篇。
   - 知识页以“问答助手”为主入口，不以文章方格浏览为主。
   - 支持检索、来源引用和结合用户上下文的知识问答。
   - 配置 LLM 时使用“知识检索 + 大模型生成”的 RAG 路径，未配置时保留稳定 fallback。
   - 输出结构固定为：30 秒看懂、3 分钟解释、可以怎么做、何时找现实帮助。

2. 测试中心 MVP
   - 支持测试列表、开始测试、提交答案、完成测试。
   - 至少交付 2 个测试：今日状态测试、16 型人格风格测试自研版。
   - 结果页必须能一键进入对话，并把测试结果作为上下文。

3. 情绪记录与趋势
   - 首页可提交 mood_score、anxiety_score、energy_score、sleep_quality、tags、note。
   - 支持 7 天和 30 天趋势。
   - 前端能展示趋势摘要和高频标签。

4. 记忆中心
   - 用户可查看、编辑、删除、清空可见记忆。
   - 用户可切换记忆模式：关闭、只记摘要、长期记忆。
   - 对话引用记忆时，用户能在页面上看到“被引用的记忆提示”。

5. SSE 流式体验补齐
   - 前端使用 `/chat/threads/{thread_id}/stream` 渲染 token。
   - 展示 graph_update、风险等级、最终 suggested_actions。
   - 网络失败时回落到非流式发送。

6. 安全评测集
   - 建立至少 50 条安全测试样例。
   - 覆盖 L0、L1、L2、L3、青少年模式、睡前场景、测试结果场景。
   - 高风险输入不得进入知识、测试、动漫或普通陪伴流程。

### 4.2 P1 尽量做

- 动漫角色测试 Beta 的数据模型和接口草案。
- 用户反馈接口：对知识答案、测试结果、AI 回复做 1-5 分反馈。
- 每周情绪小结生成。

### 4.3 本 Sprint 不做

- 动漫角色完整角色库和分享卡片。
- pgvector RAG 和大规模向量检索。
- 后台管理系统。
- App Store / 应用商店发布。
- 医疗诊断、处方、临床治疗建议。
- 13 岁以下儿童版本。

## 5. 交付物

### 5.1 前端交付

- Bottom Tab 扩展为：首页、对话、测试、知识、我的。
- 首页情绪 check-in 组件。
- 情绪趋势卡片，支持 7 天 / 30 天切换。
- 知识页：聊天式问答、推荐问题、答案来源、来源详情、继续聊天入口。
- 测试页：测试列表、答题页、结果页、结果继续聊天入口。
- 记忆中心：列表、编辑、删除、清空、记忆模式设置。
- 对话页：SSE 流式渲染、风险状态提示、知识/测试上下文入口。

### 5.2 后端交付

- knowledge_articles 种子数据和检索服务。
- `/api/v1/knowledge/search`
- `/api/v1/knowledge/articles/{article_id}`
- `/api/v1/knowledge/ask`
- tests、test_questions、test_options、test_attempts、test_answers、personality_type_profiles 数据结构。
- `/api/v1/tests`
- `/api/v1/tests/{test_id}`
- `/api/v1/tests/{test_id}/attempts`
- `/api/v1/tests/attempts/{attempt_id}/answers`
- `/api/v1/tests/attempts/{attempt_id}/complete`
- `/api/v1/tests/history`
- mood 趋势按 7d / 30d 聚合。
- 安全评测脚本和样例数据。

### 5.3 Agent 交付

- knowledge 问答 agent/service 第一版：检索知识库、调用 LLM 生成答案、返回引用来源。
- 心理咨询师 agent 与知识问答 agent 先做职责分离，不做复杂多 agent 编排。
- test_interpretation_node 第一版。
- memory_retrieval 排序规则第一版。
- memory_candidate_extract 从“只写摘要”升级为按类型提取：
  - preference
  - session_summary
  - recurring_trigger
  - support_strategy
  - safety_summary
- 高风险场景统一中断普通路径。

### 5.4 数据库交付

- `database/migrations/0004_knowledge.sql`
- `database/migrations/0005_tests.sql`
- `database/migrations/0006_user_settings_and_feedback.sql`
- 种子数据：
  - 首批知识文章不少于 20 篇
  - 今日状态测试题目
  - 16 型人格风格测试题目
  - 16 型结果 profile 文案
  - 安全评测样例

### 5.5 文档交付

- 更新 `资料/backend-openapi.yaml`
- 更新 `资料/frontend-api.yaml`
- 新增或更新本地联调说明
- 新增安全评测说明
- Sprint 2 Demo 脚本

## 6. Sprint 2 Demo 验收场景

Sprint 评审现场必须跑通以下场景：

1. 用户注册或登录，进入首页。
2. 用户提交今日状态：心情 2 分、焦虑 4 分、标签为“焦虑 / 疲惫”。
3. 首页趋势卡展示 7 天趋势摘要和高频标签。
4. 用户进入知识页，直接提问“焦虑依恋和太喜欢一个人有什么区别？”。
5. 知识问答返回结构化答案，并展示引用来源、行动建议和现实求助边界。
6. 用户点击“带到咨询对话里聊”，进入对话页，AI 能带着知识上下文回应。
7. 用户进入测试页，完成今日状态测试。
8. 测试结果展示当前状态、风险提示、建议行动，并可继续聊天。
9. 用户完成 16 型人格风格测试自研版，得到非官方人格风格结果。
10. 用户在结果页点击继续聊天，AI 能解释结果但不把结果当成标签定论。
11. 用户进入记忆中心，看到会话摘要记忆，完成编辑、删除和清空操作。
12. 用户把记忆模式切换为关闭，再发送一轮对话，系统不新增长期记忆。
13. 用户输入“我真的不想活了”，系统判定 L2 或 L3，前端打开安全提示，后端写入 risk_events。

## 7. Backlog

| Epic | 关键任务 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E1 接口契约整理 | 对齐 backend-openapi 与 frontend-api，补齐 knowledge/tests/settings | P0 | 前后端按同一字段联调 |
| E2 知识库 MVP | 文章表、种子数据、搜索、详情、ask | P0 | 搜索能返回可读详情，ask 能输出结构化回答 |
| E3 测试中心 MVP | 测试表、题目、选项、作答、结果生成 | P0 | 状态测试和 16 型测试可完成并生成结果 |
| E4 结果回流对话 | 知识/测试结果创建或复用 thread，带上下文进入 chat | P0 | AI 回复能引用结果但不贴标签 |
| E5 情绪趋势 | mood 创建、7d/30d 聚合、趋势摘要 | P0 | 首页能展示趋势和高频标签 |
| E6 记忆中心 | 记忆 CRUD、记忆模式设置、引用提示 | P0 | 用户可控记忆，关闭后不再写入 |
| E7 SSE 体验 | token 渲染、final 状态、失败回落 | P0 | 用户能看到逐步输出，失败不丢消息 |
| E8 安全评测 | 样例集、脚本、回归检查 | P0 | L2/L3 不进入普通功能流 |
| E9 动漫 Beta 草案 | 数据模型、接口草案、版权边界 | P1 | 能进入 Sprint 3 实现 |

## 8. 两周排期

- Day 1：冻结 Sprint 2 接口契约，更新 OpenAPI 和前端 API 文档。
- Day 2：新增 knowledge 数据结构、种子数据和 search/detail API。
- Day 3：实现 knowledge ask，并接入前端知识页。
- Day 4：新增 tests 数据结构、状态测试和 16 型测试种子数据。
- Day 5：实现测试作答、完成、结果生成和历史记录。
- Day 6：前端测试中心、结果页、结果回流对话。
- Day 7：记忆中心和用户设置接口，补齐记忆模式开关。
- Day 8：情绪趋势前端展示，SSE 流式体验和失败回落。
- Day 9：安全评测集、青少年模式专项校验、知识/测试高风险拦截。
- Day 10：联调、回归测试、文档补齐、Sprint Demo。

## 9. API 增量草案

### 9.1 Knowledge

- `GET /api/v1/knowledge/search?q=焦虑&category=emotion`
- `GET /api/v1/knowledge/articles/{article_id}`
- `POST /api/v1/knowledge/ask`
- `GET /api/v1/knowledge/gaps?status=open`
- `POST /api/v1/knowledge/gaps/{gap_id}/resolve`

`ask` 请求：

```json
{
  "question": "焦虑依恋和太喜欢一个人有什么区别？",
  "use_my_context": true,
  "thread_id": "optional-thread-id"
}
```

`ask` 响应：

```json
{
  "answer": {
    "summary_30s": "简短解释",
    "explanation_3min": "生活化解释",
    "actions": ["一个可执行动作"],
    "seek_help_when": ["需要现实帮助的情况"]
  },
  "related_articles": [],
  "coverage_status": "sufficient",
  "confidence": "high",
  "source_refs": [
    {
      "source_name": "NIMH",
      "source_url": "https://www.nimh.nih.gov/...",
      "license": "public-domain-text",
      "article_id": "uuid",
      "article_title": "焦虑是什么",
      "chunk_id": "uuid",
      "chunk_index": 0,
      "score": 72
    }
  ],
  "gap_id": null,
  "continue_chat_payload": {
    "mode": "knowledge",
    "context_type": "knowledge_article"
  }
}
```

### 9.2 Tests

- `GET /api/v1/tests`
- `GET /api/v1/tests/{test_id}`
- `POST /api/v1/tests/{test_id}/attempts`
- `POST /api/v1/tests/attempts/{attempt_id}/answers`
- `POST /api/v1/tests/attempts/{attempt_id}/complete`
- `GET /api/v1/tests/history`

完成测试响应必须包含：

```json
{
  "attempt_id": "uuid",
  "test_code": "sixteen_type",
  "result_code": "INFJ_like",
  "result_title": "洞察型陪伴者",
  "summary": "这是一面镜子，不是对你的定义。",
  "strengths": [],
  "blind_spots": [],
  "suggested_actions": [],
  "continue_chat_context": {
    "mode": "test",
    "context_type": "test_result"
  }
}
```

### 9.3 Settings

- `PATCH /api/v1/me/settings`

请求：

```json
{
  "memory_mode": "summary_only",
  "companion_style": "gentle",
}
```

## 10. 安全要求

### 10.1 知识与测试安全边界

- 知识回答不能输出诊断结论。
- 测试结果不能使用“确诊”“你就是某某疾病”等措辞。
- 16 型测试必须标注“自研非官方人格风格探索”。
- 状态测试只做风险提示和行动建议，不做临床判断。
- 高风险输入出现时，不继续测试、知识、动漫或娱乐流程。

### 10.2 青少年模式

- 语言更短、更具体。
- 高风险时更早建议联系可信任大人。
- 不鼓励用户与现实支持系统对立。
- 不做成人化、暧昧化、拟恋爱化陪伴。

### 10.3 数据与隐私

- 记忆必须可见、可改、可删、可关闭。
- 关闭记忆后不得新增 user_visible 长期记忆。
- safety_summary 可作为 internal_safety 记忆，但不能在普通记忆中心直接展示。
- 测试和情绪数据不得用于“诊断”文案。

## 11. 测试与评测

### 11.1 自动化回归

- 后端：pytest 覆盖 auth、chat、memory、mood、knowledge、tests、safety。
- 前端：`npm run check` 必须通过。
- API：OpenAPI 文档与实际路由字段保持一致。

### 11.2 人工评测集

至少准备：

- 20 条普通倾诉样例
- 10 条焦虑 / 睡眠样例
- 10 条知识问答样例
- 10 条测试结果解读样例
- 50 条安全样例，其中 L2/L3 不少于 20 条

### 11.3 体验验收

- 知识答案读起来像科普和自助支持，不像医疗诊断。
- 测试结果有解释、有下一步建议、不过度贴标签。
- 记忆引用自然，用户能理解 AI 为什么“记得”。
- 流式输出不卡死，失败时不丢用户输入。

## 12. 风险与缓解

- 风险：Sprint 2 同时做知识、测试、记忆和情绪，范围偏大。
- 风险：测试结果被用户理解成诊断。
  - 缓解：结果文案统一使用“倾向、可能、镜子、探索”，禁止“确诊、病、治疗结论”。
- 风险：知识回答幻觉。
  - 缓解：先用白名单种子知识文章，ask 必须引用内部文章结构，不做开放式医疗问答。
- 风险：记忆写入过多导致用户不信任。
  - 缓解：只在会话结束或明确有长期价值时写入，并在记忆中心可见可删。
- 风险：高风险从知识/测试路径绕过。
  - 缓解：所有用户输入统一先过 risk_classifier，再决定是否允许继续业务流程。

## 13. Definition of Done

- `GET /health` 返回 200。
- 登录、注册、刷新 token、退出登录可用。
- 首页可提交情绪记录并展示 7d/30d 趋势。
- 知识搜索、详情、ask 可用。
- 状态测试和 16 型人格风格测试可完成并生成结果。
- 知识和测试结果可回流到对话。
- 对话 SSE 流式体验可用，失败可回退非流式。
- 记忆中心可查看、编辑、删除、清空。
- 记忆模式关闭后不新增可见长期记忆。
- L2/L3 输入强制进入安全流程并写入 risk_events。
- 青少年模式高风险话术通过人工检查。
- 后端测试通过。
- 前端 `npm run check` 通过。
- `资料/backend-openapi.yaml` 和 `资料/frontend-api.yaml` 已更新。

## 14. Sprint 2 产出文件清单

- `资料/Sprint2计划.md`
- `资料/backend-openapi.yaml`
- `资料/frontend-api.yaml`
- `资料/安全评测集开发计划.md`
- `database/migrations/0004_knowledge.sql`
- `database/migrations/0005_tests.sql`
- `database/migrations/0006_user_settings_and_feedback.sql`
- `backend/app/api/v1/endpoints/knowledge.py`
- `backend/app/api/v1/endpoints/tests.py`
- `backend/app/services/knowledge_service.py`
- `backend/app/services/test_service.py`
- `backend/app/graphs` 中知识和测试解释相关节点
- `frontend/src/api/endpoints.ts`
- `frontend/src/types/api.ts`
- 前端知识页、测试页、记忆中心相关组件
