# frontend/AGENTS.md

前端是 Vite + React + TypeScript 应用，代码主要在 `src/`。

## 代码边界
- API 客户端和接口辅助在 `src/api/`。
- 组件在 `src/components/`。
- 路由入口在 `src/routes/`。
- 样式和设计变量在 `src/styles/`。
- 类型定义在 `src/types/`。

## 工作原则
- 改动尽量局部，优先复用现有组件、类型和样式。
- 后端接口变更时，同步检查 `src/api/` 和 `src/types/`。
- 不要编辑 `dist/`、`node_modules/` 之类的生成内容。

## 本地开发
- 安装依赖：`npm install`
- 开发启动：`npm run dev`
- 默认开发地址是 `http://localhost:5173`

## 验证
- 前端改动优先跑 `npm run check`
- 需要时再跑 `npm run build`
- 涉及页面交互或数据流时，确认和后端的契合度
