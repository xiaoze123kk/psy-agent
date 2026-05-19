# Sprint 3 计划文档

## 1. Sprint 核心目标

Sprint 3 的目标是把 Sprint 1 与 Sprint 2 已经形成的“登录、文本陪伴、知识问答、测试中心、记忆、情绪趋势、安全分流”闭环，收口成一个更完整的 MVP 演示版本：

首页状态记录
→ 文本对话 / 知识问答 / 测试结果回流
→ 测试结果可生成分享卡
→ 用户可反馈内容质量
→ 每周情绪小结可回看
→ 高风险场景统一安全分流

一句话目标：


## 2. Sprint 2 当前基线

当前代码和文档已经具备以下基础：

- 前端：Vue 3 + Vite + TypeScript，已有首页、对话、测试、知识、我的页，以及 SSE 流式对话体验。
- 后端：FastAPI，已有鉴权、对话线程、消息、记忆、情绪记录与趋势、知识搜索/问答、测试中心、安全资源和危机事件接口。
- Agent：LangGraph 已有风险识别、意图识别、陪伴回复、危机回复、摘要、记忆候选和安全路由。
- 测试中心：今日状态测试和 16 型人格风格测试已可完成，结果可回流对话。
- 安全评测：`backend/tests/test_safety_evaluation.py` 已覆盖 65 条自动化安全测试方法，满足 Sprint 2 至少 50 条样例要求。

Sprint 3 不重做 Sprint 2 主链路，只补 MVP 收口能力。

## 3. 技术栈冻结

- 前端：Vue 3 + Vite + TypeScript
- 后端：Python 3.10/3.11 + FastAPI
- Agent：LangGraph Python
- 数据库：PostgreSQL 为正式目标，本地开发允许 SQLite 兜底
- LLM：DeepSeek 配置可用时调用；未配置时必须有稳定 fallback
- 接口文档：继续维护 `资料/backend-openapi.yaml` 与 `资料/frontend-api.yaml`

## 4. Sprint 3 范围

### 4.1 P0 必做

   - 支持会话创建、session_ready、listening、transcript、assistant_delta、assistant_final、session_ended、error 等事件。

2. 测试结果分享卡
   - 今日状态测试和 16 型人格风格测试结果页支持生成分享卡 payload。
   - 分享卡先使用文字和 HTML/CSS 样式，不引入第三方图片或未授权素材。
   - 分享内容必须保留“自我观察，不是诊断”的边界提示。

3. 用户反馈接口
   - 支持对 AI 回复、知识答案、测试结果提交 1-5 分反馈。
   - 可选提交标签和文字备注。
   - 反馈不改变模型回复，只用于后续评估和体验改进。

4. 每周情绪小结
   - 基于近 7 天 mood logs 和会话摘要生成周小结。
   - 配置 LLM 时可生成自然语言总结；未配置时使用稳定 fallback。
   - 小结必须避免诊断措辞，只输出观察、趋势和可执行建议。

5. 安全回归
   - 青少年模式高风险回复必须保留现实成人支持入口。

### 4.2 P1 尽量做

- 反馈数据的简单统计视图或本地调试输出。
- 每周小结入口与首页趋势卡联动。
- 分享卡下载为图片的技术验证。

### 4.3 本 Sprint 不做

- 动漫人物测试 Beta。
- 动漫官方图片、截图、角色立绘或第三方素材。
- 依恋测试、大五人格等新增测试类型。
- 完整运营后台。
- App Store / 应用商店发布。
- 医疗诊断、处方、临床治疗建议。

## 5. 交付物

### 5.1 前端交付

- 测试结果分享卡：支持今日状态测试和 16 型人格风格测试。
- 反馈入口：对 AI 回复、知识答案、测试结果提交评分。
- 每周情绪小结卡片：展示近 7 天小结、主要标签和建议行动。

### 5.2 后端交付

- `POST /api/v1/feedback`
- `GET /api/v1/moods/weekly-summary`

### 5.3 Agent 交付

- 每周小结复用 mood logs、thread summary 和安全边界模板。
- 测试结果分享文案不得输出诊断或固定标签判断。

### 5.4 文档交付

- 新增 `资料/Sprint3计划.md`
- 更新 `资料/backend-openapi.yaml`
- 更新 `资料/frontend-api.yaml`
- Sprint 3 Demo 脚本纳入本计划文档

## 6. Sprint 3 Demo 验收场景

Sprint 评审现场必须跑通以下场景：

1. 用户登录，进入首页。
2. 用户提交今日状态记录，首页展示趋势摘要。
3. 用户打开每周情绪小结，看到近 7 天观察和行动建议。
4. 用户进入对话页，发送普通倾诉，AI SSE 流式回复。
8. 用户完成今日状态测试或 16 型人格风格测试。
9. 结果页生成分享卡，分享卡包含边界提示。
10. 用户在测试结果页点击继续聊天，AI 能解释结果但不贴标签。
11. 用户对 AI 回复或测试结果提交 1-5 分反馈。

## 7. Backlog

| Epic | 关键任务 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E4 分享卡 | 测试结果生成文字/HTML/CSS 分享卡 payload | P0 | 状态测试和 16 型测试均可生成 |
| E5 反馈接口 | 内容评分、标签、备注入库或稳定记录 | P0 | 可对三类目标提交反馈 |
| E6 每周小结 | 近 7 天 mood 小结和行动建议 | P0 | 无 LLM 配置时仍有 fallback |
| E7 回归测试 | 安全评测、后端 pytest、前端 check | P0 | 主链路不回退 |

## 8. 三天 AI 辅助排期

- Day 3（2026-05-06）：回归 Sprint 1/Sprint 2 主链路；跑安全评测、后端 pytest、前端 check；整理 Sprint 3 Demo。

## 9. API 增量草案

### 9.2 Feedback

- `POST /api/v1/feedback`

请求：

```json
{
  "target_type": "assistant_message",
  "target_id": "message-id",
  "rating": 4,
  "tags": ["有帮助", "语气合适"],
  "note": "希望再短一点"
}
```

响应：

```json
{
  "feedback_id": "feedback-id",
  "status": "recorded"
}
```

### 9.3 Weekly Mood Summary

- `GET /api/v1/moods/weekly-summary`

响应：

```json
{
  "range": "7d",
  "summary": "这周你的情绪整体偏紧绷，焦虑和疲惫出现得比较多。",
  "top_tags": ["焦虑", "疲惫"],
  "suggested_actions": ["选一天提前 30 分钟结束学习任务", "睡前做一次低刺激放松"],
  "generated_by": "fallback"
}
```

### 9.4 Share Card

分享卡由前端本地生成，不新增后端接口。

输入使用 `CompleteAttemptResponse`，输出为：

```json
{
  "title": "我的今日状态观察",
  "subtitle": "这是一面镜子，不是诊断",
  "summary": "最近更需要温和地照顾自己。",
  "highlights": ["压力偏高", "需要补充休息"],
  "disclaimer": "结果仅供自我观察，不代表诊断。"
}
```

## 10. 安全要求

- 测试结果分享卡不得出现“确诊”“治疗结论”“你就是某种病”等措辞。
- 每周情绪小结只能做观察和建议，不做临床判断。
- 青少年模式高风险场景必须建议联系可信任大人。

## 11. 测试与评测

### 11.1 自动化回归

- 后端：`python -m pytest`
- 安全专项：`python -m pytest tests/test_safety_evaluation.py`
- 前端：`npm run check`

### 11.2 新增测试

- feedback 入参校验和记录测试。
- weekly summary 无数据、有数据、fallback 三类测试。
- share card 文案边界测试。

### 11.3 人工验收

- 分享卡看起来像自我观察，而不是心理诊断报告。
- 反馈提交流程短，不打断主要使用路径。
- 周小结文案温和、具体、可执行。

## 12. 风险与缓解

- 风险：分享卡被理解成诊断结论。
  - 缓解：分享卡固定展示边界提示，禁止诊断措辞。
- 风险：三天排期压缩导致联调不足。
  - 缓解：P0 只做协议验证和 MVP 收口，非核心能力放 P1。

## 13. Definition of Done

- `GET /health` 返回 200。
- 登录、注册、刷新 token、退出登录可用。
- 文本聊天和 SSE 流式体验可用。
- 知识问答、今日状态测试、16 型人格风格测试主链路不回退。
- 测试结果分享卡可生成且不包含诊断措辞。
- 用户反馈可提交。
- 每周情绪小结可返回 fallback。
- L2/L3 输入强制进入安全流程并写入 risk_events。
- 后端测试通过。
- 前端 `npm run check` 通过。
- `资料/backend-openapi.yaml` 和 `资料/frontend-api.yaml` 已更新。

## 14. Sprint 3 产出文件清单

- `资料/Sprint3计划.md`
- `资料/backend-openapi.yaml`
- `资料/frontend-api.yaml`
- feedback 后端 endpoint 与前端调用方法
- weekly summary 后端 endpoint 与前端展示入口
- 测试结果分享卡前端本地生成方法
