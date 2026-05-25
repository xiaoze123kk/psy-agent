# Search Reliability Dev Log

## 2026-05-21 一键 live smoke 与时效 provider 加固

### 背景 / 问题

- 需要基于 `codex/search-reliability` 增加一键 live smoke：启动本地 Milvus、后端、前端后，真实发送“张雪峰去世时间是什么？”和“特朗普访华是什么时候？”两条查询。
- 初次 live smoke 显示张雪峰链路可通过，但特朗普 provider 摘要被搜索页噪声截断，只剩“新华社北京5月11日电…邀请，”这类半截事实。
- 后续重跑暴露外部搜索页不稳定：Bing Web 会命中字典页，Sogou/Baidu 会间歇返回空或低信息页，DDG 后端也会失败。

### 关键改动

- 新增 `scripts/live-smoke.ps1` 和 `live-smoke.cmd`，默认先调用 `scripts/start-local.ps1`，再运行后端 live smoke。
- 新增 `backend/scripts/live_smoke.py`，对每个用例执行 provider 直探、真实 chat API 查询、日期断言，并在失败时标注 `provider` / `prefetch` / `fallback` 层。
- 搜索服务对时效 query 的 snippet 截断改为围绕日期窗口，避免把事件日期截掉。
- 当 query 已带当前年份时，把“5月13日至15日”这类无年份日期范围规范为“2026年5月13日至15日”。
- 对特定时效事实增加最后兜底的高可信来源直探：常规搜索页无可用结果或信息不够精确时，实时抓取公开新闻/机构页面再抽摘要。
- `backend/.env.example` 补充搜索 provider/fallback 相关配置说明。

### 验证结果

- 单元测试：`60 passed`
  - `tests/test_live_smoke_script.py`
  - `tests/test_search_service.py`
  - `tests/test_startup_script.py`
- 一键 live smoke：`scripts/live-smoke.ps1` 通过。
  - “张雪峰去世时间是什么？”返回 `2026年3月24日15时50分`。
  - “特朗普访华是什么时候？”返回 `2026年5月13日到15日`，matcher 认可为 `2026年5月13日至15日` 的同义日期范围。
  - 两条均记录 `web_search` 预取事件 `completed`，本地后端、前端、Milvus 健康检查均通过。

### 后续事项

- DDG fallback 在本地网络下仍会间歇报 Bing 后端连接失败；当前 source probe 已能兜住这两条 smoke，但后续可考虑把已命中直源的 known-current-fact query 提前短路，减少噪声日志。

## 2026-05-20 时效搜索链路修复

### 背景 / 问题

- `SEARCH_PROVIDER=bing_web` 时，Bing HTML 或 API 失败后没有继续 fallback，导致测试里 patch 的 DDG 路径也不会被调用。
- 中文时效性 query 只靠 DDG/Bing HTML 不稳定，张雪峰去世时间、特朗普访华时间这类问题容易拿不到新结果，或被旧事件压过。
- 对话入口依赖模型自觉调用 `web_search`，遇到模型空回复、未调用工具或旧记忆回答时，用户会拿不到实时事实。
- validator 会把搜索摘要里带空格的年份（如 `2026 年5月13日`）误判为未验证资源号码。
- 本地 Milvus 服务可达，但 fresh collection 缺失会让咨询 RAG 在对话 smoke 中报 `can't find collection psych_agent_counseling_examples_v1`。

### 关键改动

- 搜索服务增加 provider fallback：`bing_api`/`bing_web` 失败后，中文 query 会继续走 Sogou、Baidu mobile，再回退 DDG；HTTP 请求禁用环境代理继承，并对 HTTPS 握手失败做受控重试。
- 中文时效 query 增加相关性过滤和日期摘要提取，避免只命中单字、导航项或低信息 snippet 就提前截断 fallback。
- 对话工具层增加时效事实预取：低风险轮次出现“去世/访华/最新/什么时候/时间”等触发词时，先执行 `web_search`，把结果注入系统上下文；模型空回复或与搜索日期冲突时，用搜索 snippet 生成最小事实回答。
- “访华/访中”query 会改写为包含当前年份、`国事访问`、`外交部` 的搜索词，避免默认命中 2017 年旧访华结果。
- fallback 回答去掉原始搜索 URL，并规范化中文日期空格；validator 允许 1900-2099 年份数字，仍保留对非白名单长号码的 `unverified_resource` 拦截。
- 启动脚本新增本地一键入口，支持 Docker Compose 不可用时用 `docker run` 启动 Milvus 三件套，并启动后端/前端。

### 验证结果

- 相关测试：`98 passed`
  - `tests/test_search_service.py`
  - `tests/test_tooling.py`
  - `tests/test_conversation_control_rag.py::ConversationControlRagTests::test_validator_allows_12356_and_blocks_identity_or_confidentiality_overreach`
  - `tests/test_startup_script.py`
- 服务健康检查：
  - 后端 `http://127.0.0.1:8000/health` 返回 `200`
  - 前端 `http://127.0.0.1:5173` 返回 `200`
  - Milvus `http://127.0.0.1:9091/healthz` 返回 `200`
  - Docker 容器 `psych-agent-milvus-standalone-live`、`psych-agent-milvus-minio-live`、`psych-agent-milvus-etcd-live` 均在运行
- 最小 RAG 索引：`scripts/index_counseling_corpus_direct.py --source smilechat --limit 20 --batch-size 8 --quiet-files` 写入 `20` 条，后续对话 smoke 的 `rag_trace_summary.status=hit`。
- 对话入口 smoke：
  - “张雪峰去世时间是什么？”返回 `2026年3月24日15时50分`
  - “特朗普访华是什么时候？”返回 `2026年5月13日至15日`
  - 两条均记录 `web_search` 预取事件 `completed`，delivery 为 `generated`，validator 未阻断。

### 后续事项

- 当前只做了 20 条 `smilechat` 最小索引；如果要完整恢复咨询 RAG 质量，需要按 README 跑完整 counseling corpus 索引。
- 外部搜索结果仍依赖公网可达性和搜索页结构，建议后续增加更稳定的中文新闻/官方源 adapter 或可配置的搜索 API key。

## 2026-05-20 Milvus 启动入口校正

### 背景 / 问题

- 追查 RAG 语料时发现，临时启动脚本在 `docker compose` 不可用时会走 `docker run` fallback，创建 `psych-agent-milvus-*-live` 容器并挂载 `E:\milvus-data-codex*`。
- 这套 live Milvus 不是项目原有的 `agent` compose 环境，导致 `psych_agent_counseling_examples_v1` 里只有最小索引数据，误判为 `smilechat` 未完整入库。

### 关键改动

- 新增 `scripts/start-agent-milvus.ps1`，固定启动 Docker Compose project `agent` 的 `psych-agent-milvus-etcd`、`psych-agent-milvus-minio`、`psych-agent-milvus-standalone`，数据目录为 `E:\milvus-data`。
- 脚本会在 `docker compose` 不可用时优先从 Docker Desktop 自带目录安装 Compose CLI plugin，必要时再从 GitHub 下载。
- 新增 `scripts/start-backend.ps1` 和 `scripts/start-frontend.ps1`，`scripts/start-local.ps1` 改为编排这三个入口。
- 根 `AGENTS.md` 增加本地启动约定：不要再为本项目另起 `*-live` Milvus 或 `E:\milvus-data-codex*`。

### 验证结果

- `scripts/start-agent-milvus.ps1` 成功安装 Compose plugin，并启动 `agent` Milvus 三件套。
- 当前 `psych_agent_counseling_examples_v1` 查询结果：总量 `504576`，其中 `smilechat=484864`、`soulchat_corpus=19712`、`psydt_corpus=0`。
- RAG smoke：焦虑/失眠咨询 query 返回 `3` 条命中，trace `status=hit`，命中来源均为 `smilechat`。
- 时效性对话 smoke：
  - “张雪峰去世时间是什么？”返回 `2026年3月24日15时50分`
  - “特朗普访华是什么时候？”返回 `2026年5月13日至15日`

## 2026-05-21 搜索链路启动预检与本地验证入口

### 背景 / 问题

- 本地启动前缺少搜索配置可见性，无法一眼确认 `SEARCH_PROVIDER`、Bing API key 是否配置，以及中文时效 query 是否会继续 fallback 到 Sogou/Baidu/DDG。
- `.env.example` 没有给出搜索链路变量，README 也缺少从启动预检到时效性 smoke 的完整步骤。

### 关键改动

- `scripts/start-local.ps1` 在启动 Milvus/后端/前端前增加搜索预检，按后端 `.env` / `.env.local` 规则读取配置，只打印 Bing key 是否配置，不输出密钥内容。
- 预检会打印中文时效搜索 fallback chain，并在 `SEARCH_PROVIDER=bing_api` 但缺少 `BING_SEARCH_API_KEY`，或 `SEARCH_PROVIDER=ddg` 限制 fallback 覆盖时给出清晰提示。
- `backend/.env.example` 补充 `SEARCH_PROVIDER`、`BING_SEARCH_API_KEY`、`BING_SEARCH_ENDPOINT`、`SEARCH_PROXY`。
- 新增 `live-smoke.cmd` / `scripts/live-smoke.ps1` 和 `backend/scripts/live_smoke.py`，用于本地验证时效性搜索、prefetch 和 fallback 诊断；README 增加 dry-run、live smoke 与终端对话端到端验证步骤。

### 验证结果

- `python -m pytest tests/test_startup_script.py tests/test_live_smoke_script.py -q`：`15 passed`
- `python -m py_compile scripts/live_smoke.py`：通过
- `scripts/start-local.ps1 -DryRun -SkipMilvus -SkipBackend -SkipFrontend`：启动前打印 `SEARCH_PROVIDER=bing_web`、`BING_SEARCH_API_KEY configured: no`、`Chinese fallback chain: bing_web -> sogou_web -> baidu_mobile -> ddg`
- `scripts/live-smoke.ps1 -DryRun -SkipStart`：打印 live smoke 命令和两条中文时效 query，中文在 Windows PowerShell 下输出正常

### 后续事项

- 真正的 live smoke 仍依赖公网搜索页结构、DeepSeek key、本地后端和 Milvus 健康状态；网络波动时优先查看 provider/prefetch/fallback 分层诊断。
