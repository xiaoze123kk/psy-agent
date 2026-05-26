# Auth Runtime Schema Dev Log

## 2026-05-26 注册失败与认证表结构补齐

### 背景/问题

- 前端注册页显示“注册失败，请检查输入。”，后端实际返回 `500 Internal Server Error`。
- 后端日志显示 PostgreSQL 查询 `users.token_version` 时失败，当前本地 `users` 表缺少运行时代码需要的认证字段。
- 进一步核对发现 SQL-first 迁移链也缺少 `refresh_tokens.auto_login`、`user_profiles.security_question` 和 `user_profiles.security_answer_hash`，注册流程后续会继续依赖这些字段。

### 关键改动

- 新增 `database/migrations/0016_auth_runtime_schema_alignment.sql`，补齐认证运行时字段：
  - `users.token_version`
  - `refresh_tokens.auto_login`
  - `user_profiles.security_question`
  - `user_profiles.security_answer_hash`
- 更新 `database/README.md` 的迁移执行顺序与迁移说明。
- 新增 `backend/tests/test_database_migrations.py`，防止认证运行时字段再次遗漏在 SQL 迁移链之外。
- 修复 `backend/app/api/v1/endpoints/auth.py` 注册路径：创建用户、资料和设置后先 `db.flush()`，再签发 refresh token，避免 PostgreSQL 外键在同一事务内先插入 token 而找不到用户。
- 已将同等字段补丁应用到当前本地 PostgreSQL，恢复本机注册链路。

### 验证结果

- 先运行新增测试，确认它因缺少 `token_version` 失败。
- `.\.venv\Scripts\python.exe -m pytest tests\test_database_migrations.py -q`：通过。
- `.\.venv\Scripts\python.exe -m pytest tests\test_auth_register.py -q`：通过。
- 重启后端后，调用 `POST /api/v1/auth/register`：返回 `201`，响应包含新用户信息。

### 后续事项

- 若其他环境也已存在旧 PostgreSQL 数据库，需要执行 `database/migrations/0016_auth_runtime_schema_alignment.sql`。

## 2026-05-26 登录返回体与重置时间比较修复

### 背景/问题

- 前端登录页显示“登录失败，请检查输入。”，但后端日志里对应 `POST /api/v1/auth/login` 返回 `200 OK`。
- 代码核对发现 `login()` 在创建 access token 与 refresh token 后没有返回 `LoginResponse` 和 refresh cookie，前端拿到空响应后无法建立会话。
- 密码重置页显示“重置失败，请重试。”，后端实际为 `500 Internal Server Error`。
- 后端日志显示 `password_reset` 和 `/auth/refresh` 都在比较 token `expires_at` 时触发 `TypeError: can't compare offset-naive and offset-aware datetimes`。

### 关键改动

- 补回 `login()` 的响应体和 refresh cookie，和注册、dev-session、refresh 的返回形态保持一致。
- 新增 `_aware_utc()` 与 `_utcnow_aware()`，在刷新 token 校验和密码重置 token 校验中统一用 UTC aware datetime 比较。
- 扩展 `test_auth_register.py`，覆盖：
  - 登录必须返回 session payload 和 refresh cookie。
  - refresh token 的 timezone-aware `expires_at` 不应导致 500。
  - password reset token 的 timezone-aware `expires_at` 不应导致 500。

### 验证结果

- 红灯验证：新增测试先失败，分别复现登录响应为 `None`、refresh 500、password-reset 500。
- `.\.venv\Scripts\python.exe -m pytest tests\test_auth_register.py -q`：`4 passed, 48 warnings`。
- `.\.venv\Scripts\python.exe -m pytest tests\test_auth_register.py tests\test_auth_dev_session.py tests\test_database_migrations.py tests\test_chat_endpoints.py -q`：`11 passed, 73 warnings`。
- 重启后端后，`GET http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`。

### 后续事项

- `app.db.models.utcnow()` 仍会触发 Python 3.13 的弃用警告，后续可单独把模型默认时间也统一迁移到 timezone-aware 写法。

## 2026-05-26 登录验证码错误提示修复

### 背景/问题

- 前端登录页显示“请求参数有误，请检查输入。”。
- 后端日志显示对应请求为 `POST /api/v1/auth/login` 返回 `400 Bad Request`。
- 登录接口中 `400` 来自 `_verify_captcha()`，真实后端 `detail` 是“图形验证码错误或已过期。”；前端原先按状态码把所有 400 压成通用文案，导致用户看不出是验证码问题。

### 关键改动

- 新增 `frontend/src/api/errors.ts`，统一解析 `API <status>: <json>` 错误中的 FastAPI `detail`。
- 登录/注册会话错误优先展示后端 `detail`，没有 detail 时再按状态码兜底。
- 密码找回页复用同一个 detail 解析工具，减少重复解析逻辑。
- 新增 `frontend/tests/api-errors.test.cjs` 和 `npm run test:unit`，覆盖 400 detail 优先于通用状态码文案。

### 验证结果

- 先运行新增测试，确认因缺少 `src/api/errors.ts` 失败。
- `npm run test:unit`：`2 passed`。
- `npm run check`：通过。

### 后续事项

- 若后端后续返回 Pydantic detail 数组，可再把 `extractApiErrorDetail()` 扩展为字段级中文提示。
