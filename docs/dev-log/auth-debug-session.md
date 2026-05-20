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
