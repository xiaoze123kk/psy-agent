# Auth Debug Session Dev Log

## 2026-05-20 调试入口 Missing bearer token 修复

### 背景 / 问题

- 本地前端登录页的 DEV 按钮“调试进入主页面”会直接绕过 `ProtectedAppGate`，进入会调用真实后端 API 的主界面。
- 主界面启动后会请求 `/api/v1/chat/threads`、`/api/v1/moods/trends`、`/api/v1/moods/weekly-summary` 等受保护接口；如果本地没有 access token，就会显示 `API 401: {"detail":"Missing bearer token."}`。
- 另一个相关风险是：token 被刷新逻辑清掉后，SessionProvider 的内存态可能仍停留在已认证 UI，导致后续组件继续发无 token 请求。

### 关键改动

- 后端新增 `POST /api/v1/auth/dev-session`：
  - 仅在默认开发密钥 `dev-only-change-me` 且请求来源为本机/TestClient 时启用。
  - 创建或复用 `local_debug_user`，补齐 profile/settings。
  - 返回正常的 access/refresh token pair，后续接口仍走标准 bearer 鉴权。
- 前端 `CounselingApi` 增加 `devSession()`。
- 前端 `SessionProvider` 增加 `startDebugSession()`，DEV 调试按钮改为调用 dev-session、持久化 token、再恢复当前用户。
- `tokenStore.clearTokens()` 增加清理事件；SessionProvider 监听该事件并回到匿名态，避免 UI 留在已登录但请求无 bearer 的状态。
- 移除调试按钮对主应用的无认证绕行，主界面只在真实 session 恢复后渲染。

### 验证结果

- 后端回归：`tests/test_auth_dev_session.py`，`2 passed`。
- 前端类型检查：`npm run check` 通过。
- 真实本地接口 smoke：
  - `POST http://127.0.0.1:8000/api/v1/auth/dev-session` 返回 `Bearer` token。
  - 使用 token 调用 `/api/v1/auth/me` 和 `/api/v1/chat/threads` 均返回 200。
- 浏览器验证：
  - 清空 `warp_te.access_token` / `warp_te.refresh_token` 后刷新页面。
  - 点击“调试进入主页面”后，网络面板中 `dev-session`、`auth/me`、`moods/trends`、`weekly-summary`、`chat/threads` 均为 200。
  - 页面不再显示 `Missing bearer token` 的 401 错误。

### 后续事项

- dev-session 只适合本地开发调试；生产环境必须设置非默认 `APP_SECRET_KEY`，使该入口返回 404。

## 2026-05-21 MR 冲突处理（dev-session 与 cookie refresh 兼容）

### 背景 / 问题

- 当前分支与 `main` 在认证链路发生冲突：`main` 已切换为 refresh token cookie（`rt`）方案，而本分支仍保留了 dev-session 调试入口改动。
- 直接冲突会导致前后端签名不一致（前端/测试还在期待 response body 中 `refresh_token`），影响 MR 合并。

### 关键改动

- 合并 `backend/app/api/v1/endpoints/auth.py`：保留 `main` 的 cookie refresh 流程，同时保留 `POST /api/v1/auth/dev-session`。
- `dev-session` 响应调整为与登录一致：返回 `LoginResponse`（含 access token），refresh token 通过 `Set-Cookie` 下发。
- 合并前端冲突文件：
  - `frontend/src/api/endpoints.ts` 同时保留 `devSession()` 与无参 `refreshToken()`。
  - `frontend/src/api/tokenStore.ts`、`frontend/src/app/session.tsx` 对齐 cookie refresh 新流程，并保留 `startDebugSession()`。
  - `frontend/src/app/ProtectedAppGate.tsx` 保留“调试进入主页面”走真实 dev-session 的行为，移除冲突重复属性。
- 更新 `backend/tests/test_auth_dev_session.py`，改为断言 `Set-Cookie` 中存在 `rt=`，不再断言 body 的 `refresh_token` 字段。

### 验证结果

- 后端定向测试：`pytest -q tests/test_auth_dev_session.py`，`2 passed`。
- 前端类型检查：`npm run check` 通过。

### 后续事项

- 后续如继续演进认证链路，需保持 dev-session、登录、refresh 三者在 token 传递方式上的一致性（body vs cookie）。

## 2026-05-26 main 分支注册 refresh token 外键修复

### 背景/问题

- 在 `main` 分支本地启动前后端后，前端注册页提交新用户显示“注册失败，请检查输入。”。
- 后端日志显示 `POST /api/v1/auth/register` 返回 `500 Internal Server Error`。
- 具体异常为 `refresh_tokens_user_id_fkey` 外键失败：注册接口在同一事务里创建 `users`、`user_profiles`、`user_settings` 后立即签发 refresh token，SQLAlchemy flush 时可能先插入 `refresh_tokens`，此时 PostgreSQL 还看不到对应 `users` 记录。

### 关键改动

- 在 `backend/app/api/v1/endpoints/auth.py` 的 `register()` 中，`db.add_all([user, profile, user_settings])` 后先执行 `db.flush()`，确保用户记录已持久化，再签发 refresh token。
- 新增 `backend/tests/test_auth_register.py`，通过断言签发 token 前 `User` 已进入 persistent 状态，防止注册路径再次回到 pending 状态签发 token。

### 验证结果

- 红灯验证：新增测试先失败，`inspect(user).persistent` 为 `False`。
- 修复后：`backend/.venv/Scripts/python.exe -m pytest tests/test_auth_register.py -q` 通过，`1 passed, 5 warnings`。

### 后续事项

- 仍可后续单独处理 `datetime.utcnow()` 弃用 warning；本次不扩大改动范围。

## 2026-05-26 登录成功响应缺失修复

### 背景/问题

- 用户反馈本地登录页使用已注册账号登录失败，前端只显示“登录失败，请检查输入。”。
- 复查认证链路发现，后端 `/api/v1/auth/login` 在用户名、密码和验证码校验成功后，会签发 access/refresh token 并提交事务，但函数末尾没有返回 `LoginResponse`。
- 该路径会让前端收到空响应体，`SessionProvider` 无法读取 `access_token`，于是进入登录失败分支。

### 关键改动

- 在 `backend/app/api/v1/endpoints/auth.py` 的 `login()` 成功路径补回 `LoginResponse` JSON 响应。
- 成功登录时继续通过 `Set-Cookie` 下发 refresh token，与 register、dev-session 和 refresh 流程保持一致。
- 扩展 `backend/tests/test_auth_register.py`，新增登录成功回归测试，断言响应体包含 `access_token`、`token_type`、用户名，并包含 `rt=` cookie。

### 验证结果

- 红灯验证：新增登录测试先失败，`response.json()` 为 `None`。
- 修复后：`backend/.venv/Scripts/python.exe -m pytest tests/test_auth_register.py -q` 通过，`2 passed, 13 warnings`。
- 认证相关回归：`backend/.venv/Scripts/python.exe -m pytest tests/test_auth_register.py tests/test_auth_dev_session.py -q` 通过，`4 passed, 21 warnings`。
- 本地真实后端 smoke：`/api/v1/auth/captcha` + `/api/v1/auth/login` 返回 200，响应包含 `access_token`，并设置 `rt=` refresh cookie。
- 浏览器验证：在 `http://127.0.0.1:5173/` 通过登录表单提交后进入新用户引导页，确认前端能读取登录响应并切换 session 状态。

### 后续事项

- 前端当前仍把后端具体错误折叠成通用失败提示；后续可单独改善错误提示，让验证码错误、密码错误和服务端异常更容易区分。
