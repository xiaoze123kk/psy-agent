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

## 本地启动约定
- 启动全套本地环境优先使用 `scripts/start-local.ps1` 或 `start-local.cmd`；它会按顺序启动 Milvus、后端、执行 RAG readiness check、启动前端。
- `scripts/start-local.ps1` 默认会调用 `backend/scripts/check_rag_ready.py`，确认 Milvus 可连、本地 embedding 可生成向量、`psych_agent_counseling_examples_v1` 能检索到咨询 RAG 示例；除非明确排障，不要加 `-SkipRagCheck`。
- 单独启动 Milvus 使用 `scripts/start-agent-milvus.ps1`；必须启动 Docker Compose project `agent` 中的 `psych-agent-milvus-etcd`、`psych-agent-milvus-minio`、`psych-agent-milvus-standalone`，数据目录为 `E:\milvus-data`。
- 不要为本项目另起 `*-live` Milvus 容器或临时 `E:\milvus-data-codex*` 数据目录；这会让 RAG 连接到空索引。
- 如果 `docker compose` 不可用，先安装或启用 Docker Compose CLI plugin，再启动 `agent` 这套容器。
- 单独启动后端使用 `scripts/start-backend.ps1`，默认端口 `8000`；脚本默认以无 `--reload` 的单进程方式启动，并设置本地 embedding worker/超时环境，以保证 RAG 可用。只有明确需要热重载调试时才加 `-Reload`。
- 单独启动前端使用 `scripts/start-frontend.ps1`，默认端口 `5173`。

## 通用忽略
- 不要编辑构建产物、缓存、虚拟环境、依赖安装目录或日志。
- 常见例子包括 `node_modules/`、`.venv/`、`frontend/dist/`、`.pytest_cache/`、`*.log`、`.env*`、`backend/data/*.db`。

## 开发日志
- 每次开发都要写 dev-log：优先在 `docs/dev-log/` 中找到相关主题文件续写；没有合适文件时新建主题明确的 Markdown 文件。
- dev-log 至少记录日期、背景/问题、关键改动、验证结果和后续事项。
- 不要在 dev-log 中写入密钥、令牌、完整隐私数据或大段运行日志；只保留必要的结论和可复现线索。

## Git 提交
- commit message 使用中文描述，并保持 Conventional Commit 格式：`type: 中文简短说明`。
- `type` 使用常见类型，如 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`。
- 示例：`feat: 重构后端风控策略`、`docs: 记录提交信息规范`。
