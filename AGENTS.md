# AGENTS.md

这个仓库是一个心理咨询 agent 项目。根目录只放跨目录的通用约定，具体规则优先看离代码最近的 `AGENTS.md`。

## 通用原则
- 只改与你当前任务相关的目录。
- 不要覆盖用户已有改动或无关生成文件。
- 优先沿用现有结构和各目录 README 中的约定。
- 优先使用可用的 superpower skill，并按技能说明执行。
- 涉及跨层接口时，同时核对相关子目录说明。

## 目录导向
- `backend/`：见 `backend/AGENTS.md`
- `frontend/`：见 `frontend/AGENTS.md`
- `database/`：见 `database/AGENTS.md`

## 通用忽略
- 不要编辑构建产物、缓存、虚拟环境、依赖安装目录或日志。
- 常见例子包括 `node_modules/`、`.venv/`、`frontend/dist/`、`.pytest_cache/`、`*.log`、`.env*`、`backend/data/*.db`。

## Git 提交
- commit message 使用中文描述，并保持 Conventional Commit 格式：`type: 中文简短说明`。
- `type` 使用常见类型，如 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`。
- 示例：`feat: 重构后端风控策略`、`docs: 记录提交信息规范`。
