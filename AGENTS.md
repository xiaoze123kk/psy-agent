# AGENTS.md

这个仓库是一个心理咨询 agent 项目。根目录只放跨目录的通用约定，具体规则优先看离代码最近的 `AGENTS.md`。

## 通用原则
- 只改与你当前任务相关的目录。
- 不要覆盖用户已有改动或无关生成文件。
- 优先沿用现有结构和各目录 README 中的约定。
- 涉及跨层接口时，同时核对相关子目录说明。

## 目录导向
- `backend/`：见 `backend/AGENTS.md`
- `frontend/`：见 `frontend/AGENTS.md`
- `database/`：见 `database/AGENTS.md`

## 通用忽略
- 不要编辑构建产物、缓存、虚拟环境、依赖安装目录或日志。
- 常见例子包括 `node_modules/`、`.venv/`、`frontend/dist/`、`.pytest_cache/`、`*.log`、`.env*`、`backend/data/*.db`。
