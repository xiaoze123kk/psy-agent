# 前端对话列表治理迭代日志

## 2026-05-18 单一空白对话与历史堆积 spec

### 背景

左侧对话列表中连续出现多条“新的陪伴对话”，这些对话摘要为空、风险级别为 `L0`，会挤占“续聊与状态”的可读空间。当前前端点击“开始新对话”会立即调用后端创建线程，因此用户未发送消息也会污染历史列表。

### 本次改动

- 新增设计文档：`docs/superpowers/specs/2026-05-18-frontend-single-draft-conversation-design.md`。
- 明确推荐方案：前端先采用本地单例草稿，用户发送第一条消息时再创建后端线程。
- 明确大量历史对话堆积的处理方向：最近对话分组、折叠更早内容、搜索筛选、归档优先、风险线程优先保留。
- 更新根 `AGENTS.md`，要求每次开发记录 dev-log。

### 验证

- 已核对现有前端入口：`frontend/src/app/ningyu/NingyuAppShell.tsx` 中 `handleStartNewThread()` 会立即调用 `api.startThread()`。
- 已核对现有接口：`GET /api/v1/chat/threads` 当前只返回 `items`，没有分页、归档、消息数量或空线程标记。
- 本轮只写 spec 和规范，不改业务代码，不运行前端测试。

### 后续事项

1. 按 spec 制定实现计划。
2. 实现本地单例草稿和首条消息创建线程流程。
3. 增加线程列表归一化、分组和折叠。
4. 后续补充后端分页、归档、`message_count` 和 `is_empty` 字段。

## 2026-05-18 多 agent 实施计划

### 背景

在完成单一空白对话 spec 后，需要把方案拆成可交给多个 agent 的实施计划。计划需要避免多个 worker 同时编辑 `NingyuAppShell.tsx`，同时保留前端设计要求中的可扫描、低干扰侧栏体验。

### 本次改动

- 新增实施计划：`docs/superpowers/plans/2026-05-18-frontend-single-draft-conversation.md`。
- 用多 agent 边界拆分为四类任务：纯函数与 contract、CSS 视觉样式、Shell 状态集成、验证与 dev-log。
- 明确 Worker A 和 Worker B 可并行；Worker C 必须等 Worker A 的 helper API 完成；Worker D 在最终集成后负责验证。

### 验证

- 已用只读 explorer 核对 `NingyuAppShell.tsx` 的 `loadThreads()`、`loadMessages()`、`handleStartNewThread()` 和 `handleSend()` 状态流。
- 已用只读 explorer 核对左侧列表相关 CSS class、明暗主题和响应式断点。
- 本轮只写实施计划和 dev-log，不改业务代码，不运行前端测试。

### 后续事项

1. 用户确认后按计划进入 subagent-driven implementation。
2. 实现前先确保各 worker 遵守计划中的文件所有权。
3. 实现完成后运行 `npm run check`、`npm run build` 和浏览器网络验证。

## 2026-05-18 单一草稿对话实现

### 背景

根据 `docs/superpowers/specs/2026-05-18-frontend-single-draft-conversation-design.md`，左侧“开始新对话”需要从立即创建后端线程改为本地单例草稿，避免空线程堆积。

### 关键改动

- 新增 `frontend/src/app/ningyu/threadList.ts`，集中处理草稿 entry、疑似空线程折叠、最近线程分组和溢出计数。
- 新增 `frontend/src/app/ningyu/threadList.contract.ts`，用 TypeScript contract 覆盖重复空线程、风险线程、摘要线程、草稿和 50 条历史线程场景。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx`，用 draft/thread discriminated state 管理当前会话，并在草稿首条消息发送时创建后端线程。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.css`，增加草稿项、分组标题、隐藏空白对话提示和更早对话说明样式。
- 修复实现 review 中发现的竞态：切换线程会清理旧 stream 状态；草稿创建线程时有 stale guard；创建线程失败时不清空输入框。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite 产物写入 `frontend/dist/`，未手动编辑构建产物。
- 浏览器验证：`http://127.0.0.1:5175` 可打开；通过调试入口进入主页面后，连续点击“开始新对话”10 次仅显示一个“当前草稿”；发送前网络面板没有新增 `POST /api/v1/chat/threads`；输入草稿首条消息后才出现 1 次 `POST /api/v1/chat/threads`。当前调试页面没有 bearer token，该 POST 返回 401，但输入内容仍保留，符合创建失败不丢草稿的要求。
- 响应式检查：1366x768、1080x768、761x768 下左侧草稿和分组显示稳定；760x768、390x844 下左侧栏按现有移动端规则隐藏；未发现草稿项文字和风险/模式徽标重叠。
- 截图留存：`.playwright-mcp/single-draft-desktop.png`、`.playwright-mcp/single-draft-mobile.png`。

### 后续事项

1. 后端 `ThreadListItem` 后续补充 `message_count`、`is_empty` 和 `archived_at`，替代前端启发式空线程判断。
2. 历史对话超过默认展示数量后，后续接入真实分页、搜索和归档接口。
3. 在带真实登录态的环境里补一次草稿首发成功后的完整 stream 验证。

## 2026-05-18 欢迎语审美调整

### 背景

页面评审指出欢迎区中“这里已经进入标准模式，可以开始一段新对话...”的表达偏功能说明，需要更唯美一些，同时不能丢掉模式、首句引导和安全入口提示。

### 本次改动

- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx` 中 `WelcomeState` 的空状态文案。
- 将新对话欢迎语改为更柔和的陪伴式表达，保留 `${userModeLabel}`、`${primarySuggestion}` 和 `${primarySupportLabel}`。
- 顺手统一已有线程空消息提示，让它与欢迎区的语气保持一致。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- 浏览器验证：`http://127.0.0.1:5175/` 通过调试入口进入主页面后，欢迎语已更新为更柔和的陪伴式表达；在 1030x902 视口下未出现溢出或遮挡。

## 2026-05-18 欢迎语去身份化调整

### 背景

页面二次评审指出欢迎语不应出现调试用户 ID，也不应出现“标准模式”等系统模式标签。欢迎区是情绪入口，不应该让用户先看到内部状态信息。

### 本次改动

- 移除 `WelcomeState` 对 `displayName` 和 `userModeLabel` 的依赖。
- 移除 `ChatWorkspace` 透传给欢迎空状态的用户标识和模式标签。
- 将欢迎语开头改为“先把世界的声音放轻一点”，保留首句建议和右侧安全入口提示。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- 浏览器验证：`http://127.0.0.1:5175/` 通过调试入口进入主页面后，1030x902 视口下欢迎语显示为“先把世界的声音放轻一点...”，目标段落不再出现用户 ID 或模式标签。

## 2026-05-18 入场卡片每日一次

### 背景

页面评审指出“宁语 · 心灵驿站”入场卡片不应每次进入主页面都出现，而应每天只出现一次。当前 `ProtectedAppGate` 只用组件内存状态 `hasPlayedEntryTransition` 控制，页面刷新或重新挂载后会丢失当天已看过的状态。

### 本次改动

- 新增 `frontend/src/app/auth/entryTransitionFrequency.ts`，用本地日期键记录当天是否已经完成入场卡片。
- 新增 `frontend/src/app/auth/entryTransitionFrequency.contract.ts`，覆盖首次展示、同日跳过、隔日重新展示和存储不可用场景。
- 更新 `frontend/src/app/ProtectedAppGate.tsx`，初始状态读取每日标记；用户完成入场卡片后写入当天标记。

### 验证

- TDD RED：新增 contract 后，`npm run check` 因缺少 `./entryTransitionFrequency` 模块失败。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：使用预加载脚本模拟已登录用户和最小 API 响应；清除 `ningyu.entryTransition.seenDay` 后刷新，入场卡片出现；点击“轻轻推开门”后本地存储写入 `2026-05-18`；保留该标记再次刷新，同一天第二次进入不再显示入场卡片。

## 2026-05-18 安全热线真实号码

### 背景

页面评审指出右侧安全支持中的“24小时热线 400-xxx-xxxx”仍是占位号码。安全入口不能使用虚构号码，需要替换为真实存在的心理危机支持号码。

### 本次改动

- 将 `frontend/src/app/ningyu/NingyuAppShell.tsx` 中 `supportResources` 的热线号码从 `400-xxx-xxxx` 改为 `010-82951332`。
- 选择依据：公开资料中，北京心理危机研究与干预中心/北京回龙观医院将 `010-82951332` 列为心理危机干预热线，适用于手机、IP、分机用户，并提供 24 小时危机干预支持。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：`http://127.0.0.1:5175/` 通过调试入口进入主页面后，1323x902 视口下右侧安全支持卡片显示为 `24小时热线 010-82951332`。

## 2026-05-18 移除聊天区内联建议

### 背景

页面评审指出聊天消息下方的“可以接着试试”以及“把刚才的话说得更具体一点 / 帮我整理成一个小步骤”按钮可以不要。该区域是前端在有消息但没有后端建议时追加的静态 fallback，会让聊天区显得过度引导。

### 本次改动

- 移除 `frontend/src/app/ningyu/NingyuAppShell.tsx` 中聊天区内联建议的静态 fallback。
- 移除 `SuggestedActionChips` 渲染与组件。
- 移除点击内联建议后自动填充输入框的 `draftSuggestion` 状态链路。
- 保留右侧面板中的“可以试试”建议入口。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：使用预加载脚本模拟已登录用户和一段已有对话，聊天消息下方不再出现“可以接着试试”区域；右侧面板的“可以试试”建议入口仍保留。

## 2026-05-18 引导页换行脏字符修复

### 背景

调试引导页第 1 步的说明卡里出现了字面量 `` `r`n ``，影响文案观感。检索源码后确认只有 `frontend/src/app/auth/OnboardingGuide.tsx` 这一处来源。

### 本次改动

- 新增 `frontend/src/app/auth/onboardingSafetyNotice.ts`，把安全说明拆成结构化数据。
- 新增 `frontend/src/app/auth/onboardingSafetyNote.contract.ts`，约束文案中不应出现字面量 `` `r`n ``。
- 更新 `frontend/src/app/auth/OnboardingGuide.tsx`，改为逐条渲染 bullet 和边界说明，去掉脏字符。

### 验证

- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：通过“调试进入引导页”进入 step 1 后，说明卡显示为正常的多行文案，不再出现 `` `r`n ``。

## 2026-05-18 引导页分数选择反馈

### 背景

调试引导页第 6 步“心情签到”中，分数按钮点击后没有明显反馈。排查后确认 React state 会更新，按钮也会加上 `is-active` 类，但 CSS 选中态只覆盖了目标、语气和隐私按钮，漏掉了 `.debug-guide__scores button.is-active`。

### 本次改动

- 为 `frontend/src/app/auth/DebugOnboardingGuide.css` 增加分数按钮选中态，强化边框、背景、字重和阴影。
- 为 `frontend/src/app/auth/OnboardingGuide.tsx` 中分数按钮增加 `aria-pressed`，让选中状态对辅助技术可见。

### 验证

- TDD RED：样式检查脚本确认 `.debug-guide__scores button.is-active` 缺失。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：通过“调试进入引导页”走到第 6 步，点击“整体心情 5”后，5 变为 `aria-pressed=true` 并应用新的深绿背景、边框和阴影；原默认 3 取消选中。

## 2026-05-18 心情记录每日一次

### 背景

右侧“此刻心情”里的“记录心情”每次点击都会提交一条新的 mood log。产品期望该入口作为每日 check-in，同一天只记录一次，而不是每次进入或每次点击都记录。

### 本次改动

- 新增 `frontend/src/app/ningyu/moodCheckInFrequency.ts`，集中处理本地日期键、用户维度存储标记、后端趋势/最新记录是否包含今天。
- 新增 `frontend/src/app/ningyu/moodCheckInFrequency.contract.ts`，覆盖同日锁定、隔日解锁、最新记录和趋势数据判断。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx`，提交成功后写入当天标记；如果今天已记录，按钮显示“今日已记录”并禁用。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.css`，给“今日已记录”状态增加独立的柔和禁用样式。

### 验证

- TDD RED：新增 contract 后，`npm run check` 因缺少 `./moodCheckInFrequency` 模块失败。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：使用预加载脚本模拟 mood API 成功返回；第一次点击“记录心情”后只发出 1 次 `POST /api/v1/moods`，本地写入 `2026-05-18`，按钮变为“今日已记录”并禁用；刷新后同一天直接显示“今日已记录”，`POST` 次数保持 0。
- 验证结束后清理了本次写入的 `ningyu.moodCheckIn.recordedDay.local` 测试标记。

## 2026-05-18 心情记录完成态收束

### 背景

在实现“记录心情每天一次”后，已记录状态仍展示分数、标签和备注输入，会让用户误以为还可以继续改或再次记录。完成态应该收束为只读反馈。

### 本次改动

- 扩展 `frontend/src/app/ningyu/moodCheckInFrequency.ts`，新增 `shouldShowMoodCheckInControls()`，明确已记录时隐藏输入控件。
- 更新 `frontend/src/app/ningyu/moodCheckInFrequency.contract.ts`，覆盖 open 状态显示控件、recorded 状态隐藏控件。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx`，已记录时只渲染完成提示和“今日已记录”按钮，不再渲染分数、标签和备注输入。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.css`，为完成态容器补充轻量状态样式。

### 验证

- TDD RED：新增 contract 后，`npm run check` 因 `shouldShowMoodCheckInControls` 未导出失败。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：使用本地 `ningyu.moodCheckIn.recordedDay.local=2026-05-18` 模拟已记录状态，右侧心情卡中分数按钮数量为 0、标签按钮数量为 0、备注输入数量为 0，仅保留“今日已记录”按钮。
- 验证结束后清理了本次写入的 `ningyu.moodCheckIn.recordedDay.local` 测试标记。

## 2026-05-18 每日首聊建议幂等修复

### 背景

右侧“可以试试”三条建议仍然沿用旧快捷入口逻辑，点击后会直接创建后端线程，绕开前端单一草稿模型。文案也仍是固定模板，不符合“每天第一次对话由综合上下文给出建议”的目标。

### 本次改动

- 新增 spec：`docs/superpowers/specs/2026-05-18-frontend-daily-opening-suggestions-design.md`。
- 新增 `frontend/src/app/ningyu/dailyOpeningSuggestions.ts` 和 contract，集中处理每日 seenDay、同页面 StrictMode 幂等、点击后隐藏、以及基于用户模式、记忆模式、时间、心情趋势和周小结的开场建议生成。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx`，右侧建议改为“今日开场”；当天首次展示即写入 seenDay，点击任意一条后整段隐藏。
- 点击建议不再调用 `api.startThread()`，只激活本地草稿并把建议文本填入聊天输入框，后端线程仍由发送首条消息时创建。

### 验证

- TDD RED：新增 contract 后，`npm run check` 因缺少 `./dailyOpeningSuggestions` 模块失败；补 StrictMode 场景后再次因缺少 `claimDailyOpeningSuggestionsForSession` / `dismissDailyOpeningSuggestionsForSession` 失败。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0。
- 浏览器验证：`http://127.0.0.1:5175/` 清空 `ningyu.dailyOpeningSuggestions.seenDay.*` 后进入主页面，右侧出现三条“今日开场”，且不包含旧静态模板；点击任意一条后右侧建议 section 消失，左侧只出现一个“当前草稿”，输入框填入所选开场句。
- 网络验证：点击“今日开场”建议前后，网络记录中只有已有的 `GET /api/v1/chat/threads` 401 调试请求，没有新增 `POST /api/v1/chat/threads`。
- 同日刷新验证：点击建议并刷新后再次进入主页面，右侧“今日开场”不再出现。
- 验证结束后清理了本次写入的 `ningyu.dailyOpeningSuggestions.seenDay.local` 测试标记。

### 后续事项

1. 后端后续可提供专用 LLM 接口 `GET /api/v1/chat/daily-opening-suggestions`，由服务端直接综合情绪、会话摘要、记忆偏好和安全状态生成三条建议。
2. 当前前端优先使用已有 LLM 周小结和心情趋势；后端不可用或无数据时使用本地安全兜底。

## 2026-05-26 主聊天对话舞台双主题改造

### 背景

用户反馈 `main` 分支主界面不够理想，更偏好 `codex/search-reliability` 分支截图里的中间对话界面。确认范围后，本次只改已登录后的主聊天界面，不改登录、注册、引导或后端接口。

### 本次改动

- 新增规格文档和实施计划，明确主聊天界面采用居中对话舞台，并保留日间/夜间双主题。
- 新增 `frontend/tests/chat-shell-css.test.cjs` 和 `npm run test:unit`，用 CSS 合同测试防止主聊天区回退到厚重纸页样式。
- 更新 `NingyuAppShell.tsx`，把中央容器从 paper wrapper 调整为 chat stage token。
- 更新 `NingyuAppShell.css`，移除主聊天区的卷角纸页、底部锯齿和 `clip-path`，改为轻量半透明舞台。
- 为日间和夜间分别定义聊天舞台表面、细线、边框和消息气泡色彩；输入栏、悬浮控件、图运行轨迹和移动端布局同步收敛到同一视觉骨架。

### 验证

- TDD RED：`npm run test:unit` 先失败，确认当前 CSS 缺少 `.ningyu-chat__stage-token` 和舞台主题变量。
- 修复后：`npm run test:unit` 通过，`2 passed`。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0，仅保留 `module.register()` 的上游弃用提示。
- 浏览器验证：`http://127.0.0.1:5173/` 调试进入主页面后，桌面 `1440x1000` 和移动 `390x844` 均非空白；日间/夜间主题可切换，主聊天舞台分别应用日间/夜间背景和边框；`documentElement.scrollWidth - innerWidth` 为 0。
- 调试态控制台仍会出现既有 `/api/v1/auth/refresh` 401/500 与 `favicon.ico` 404，不影响本次主界面视觉改造，未纳入本次提交范围。

### 后续事项

- 图运行轨迹目前仍是展开态；后续如需要更接近产品体验，可单独设计折叠/展开策略。

## 2026-05-26 主聊天透明舞台微调

### 背景

用户反馈主聊天顶栏会遮挡“宁语手记”，且当前主聊天区域仍像一整张书页，希望不要继续使用书页形式，并让界面更透明。

### 本次改动

- 扩展 `frontend/tests/chat-shell-css.test.cjs`，约束主聊天区不再出现 `paper` wrapper、角标装饰或横线纸纹变量。
- 更新 `NingyuAppShell.tsx`，移除聊天舞台左上角装饰，并把内容容器从 `paper` 命名改为 `stage` 命名。
- 更新 `NingyuAppShell.css`，降低全局顶栏背景不透明度和高度，并为桌面聊天区增加顶部留白，避免顶栏显示时压住“宁语手记”。
- 移除主聊天大面板的横线纸纹，改为更透明的玻璃式舞台；日间/夜间舞台背景、边框和阴影整体降存在感。
- 移动端单独收回顶部留白，保持标题不被挡，同时避免小屏首屏过空。

### 验证

- TDD RED：新增 CSS/markup 合同测试后，`npm run test:unit` 因仍存在 `ningyu-chat-paper`/`ningyu-chat-corner` 失败。
- 修复后：`npm run test:unit` 通过，`3 passed`。
- `npm run check`：通过，`tsc --noEmit` exit 0。
- `npm run build`：通过，Vite build exit 0，仅保留 `module.register()` 的上游弃用提示。
- 浏览器验证：桌面 `1600x1200` 下日间主题标题距离顶栏底部约 68px，`hasPaperOrCorner=false`，无横向溢出；夜间主题同样无横向溢出并应用更透明的夜间舞台背景；移动端 `390x844` 下标题距离顶栏底部约 66px，无横向溢出。
