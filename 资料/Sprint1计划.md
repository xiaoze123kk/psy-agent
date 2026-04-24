# Sprint 1 计划文档（整合版）

## 1. Sprint 核心目标

Sprint 1 只做第一条可演示闭环：

注册或登录
→ 年龄确认
→ 新手引导
→ 进入首页
→ 创建对话
→ 发送文字消息
→ LangGraph 执行风险识别与意图识别并生成回复
→ 保存消息与风险事件
→ 生成会话摘要
→ 下次进入可继续上次会话

一句话目标：

做出一个“能登录、有青少年模式、有基础文本陪伴聊天、有 LangGraph 编排、有基础风险识别、有会话保存”的最小可用版本。

## 2. 技术栈冻结（本 Sprint 不变）

- 前端：Vue 3 + Vite + TypeScript
- 后端：Python 3.11 + FastAPI
- Agent：LangGraph（Python）
- 数据库：PostgreSQL
- 缓存：Redis（可选，不作为 Sprint 1 必要依赖）
- 接口文档：OpenAPI YAML + 前端 API 契约 YAML

## 3. Sprint 1 不做什么

以下内容全部放到后续 Sprint：

- 实时语音聊天（可保留入口占位）
- 动漫角色测试
- 16 型人格测试
- 完整知识库 RAG
- 情绪趋势可视化
- 分享卡片
- 复杂长期记忆策略
- 多模型切换
- 后台管理系统
- 应用商店上架

## 4. Sprint 1 交付物

### 4.1 前端交付

- 启动页
- 登录/注册页
- 年龄确认页
- 新手引导页
- 首页（含继续对话入口）
- 对话页（文本）
- 我的页（基础）
- SOS 页面（基础）

### 4.2 后端交付

- 用户注册、登录、当前用户接口
- 创建会话、发送消息接口
- 记忆列表与基础修改接口
- 安全资源与危机事件接口
- 基础情绪记录接口

### 4.3 Agent 交付

- main_agent_graph
- risk_classifier_node
- intent_classifier_node
- companion_response_node
- crisis_response_node
- summarize_turn_node
- 风险路由与意图路由

### 4.4 数据库交付

- users
- user_profiles
- user_settings
- conversation_threads
- messages
- risk_events
- mood_logs
- tests
- test_attempts

### 4.5 文档交付

- Sprint1 计划文档
- 后端 OpenAPI YAML
- 前端接口契约 YAML
- 本地启动与联调说明

## 5. Sprint 成功标准（验收 Demo）

Sprint 评审现场必须跑通以下场景：

1. 用户注册并登录
2. 用户选择 16-17 岁并进入 teen 模式
3. 完成新手引导进入首页
4. 点击“我想倾诉”进入对话
5. 输入“我最近压力好大，感觉没人理解我”，系统返回共情回复
6. 输入“我真的不想活了”，系统判定高风险并切换安全回复
7. 前端出现 SOS 入口，后端保存风险事件
8. 用户重新进入后可看到上次会话摘要并继续对话

## 6. Backlog（Sprint 1）

| Epic | 关键任务 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| E1 工程初始化 | 仓库结构、.env.example、本地启动脚本 | P0 | 前后端都可本地启动 |
| E2 数据与鉴权 | users/profile/settings、注册登录、当前用户 | P0 | 登录后可获取并使用 token |
| E3 Onboarding | 年龄确认、新手引导、模式写入 | P0 | 13-17 写入 teen，18+ 写入 adult |
| E4 文本聊天链路 | 创建会话、发消息、历史消息、消息落库 | P0 | 一轮对话可完整保存与回放 |
| E5 LangGraph MVP | 风险识别、意图识别、陪伴回复、危机回复、摘要 | P0 | L2/L3 强制安全分流 |
| E6 安全与 SOS | 风险事件入库、SOS 页面、青少年高风险话术 | P0 | 高风险时禁止普通陪伴回复 |
| E7 前端壳与页面 | Vue+Vite 页面骨架与 API 接入 | P0 | 前端能完成登录到聊天闭环 |
| E8 文档与测试 | API 文档、启动文档、回归测试样例 | P1 | 新成员可按文档完成本地复现 |

## 7. 两周排期（10 个工作日）

- Day 1：工程初始化、目录与规范
- Day 2：数据库初始化与注册登录
- Day 3：年龄确认与新手引导
- Day 4：会话与消息 API
- Day 5：LangGraph 主图第一版
- Day 6：前端对话页接入 API
- Day 7：高风险识别与 SOS 分流
- Day 8：会话摘要与首页续聊
- Day 9：青少年模式专项校验
- Day 10：回归测试、文档补齐、Sprint Demo

## 8. 风险与缓解

- 风险：需求扩张导致 Sprint 失控
  - 缓解：冻结范围，非闭环需求全部放 Sprint 2
- 风险：前后端接口频繁变化
  - 缓解：以后端 OpenAPI YAML 为单一接口真相源
- 风险：高风险场景误判
  - 缓解：规则拦截 + 人工测试集（至少 50 条）双重验证
- 风险：LangGraph 与 API 层耦合过深
  - 缓解：Agent 逻辑放 service/graph 层，路由层只做编排

## 9. Definition of Done 清单

- GET /health 返回 200 且 status=ok
- 聊天主链路可跑通：创建线程 + 发送消息
- 高风险输入能进入安全回复且写入 risk_events
- 会话摘要可生成并在首页展示
- 前端 Vue + Vite 可运行（npm run dev）
- 前端类型检查通过（npm run check）
- 数据库迁移脚本可执行成功
- 文档齐全且可用于新成员入组

## 10. Sprint 1 产出文件清单

- backend API 与 LangGraph 骨架代码
- database/migrations/0001_init.sql
- frontend Vue + Vite 工程骨架
- 资料/backend-openapi.yaml
- 资料/frontend-api.yaml
- 资料/Sprint1计划.md
