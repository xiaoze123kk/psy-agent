# Ningyu Frontend

这是界面，它有点好看，没了。


## Tech Stack

- React
- TypeScript
- Vite
- lucide-react
- CSS

## Quick Start

npm install
npm run dev


默认开发地址通常是：

http://localhost:5173

前端需要配合本地后端服务使用。后端启动方式见仓库的 `backend/README.md`。
## Scripts

npm run dev

## Project Structure

```text
src/
  api/              API client、endpoint helpers、token store
  app/              React app shell、session、全局状态
    auth/           登录/注册、onboarding、进入主界面过渡
    ningyu/         宁语主界面 app shell
  components/       底层共享 UI utilities
  imports/          设计稿图片和界面资源
  routes/           后续页面路由入口
  styles/           全局样式和 design tokens
  types/            API 类型定义
```

## Backend

本项目默认请求本地后端 API。开发时通常需要同时启动：

```bash
# backend/
uvicorn app.main:app --reload --port 8000
```

后端环境变量、数据库迁移和可选 Milvus 配置请查看：

- `backend/README.md`
- `database/README.md`
