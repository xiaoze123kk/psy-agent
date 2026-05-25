# database/AGENTS.md

数据库目录采用 SQL-first 迁移方式，所有迁移都放在 `database/migrations/`。

## 代码边界
- 迁移文件按编号顺序维护，不要重排历史迁移。
- 结构变更要和后端运行时表、接口约定一起看。

## 工作原则
- PostgreSQL 是持久化真源。
- Milvus 只是可重建索引，不是主存储。
- 只在确有必要时新增迁移，避免修改已发布迁移。

## 本地开发
- 迁移命令以 `database/README.md` 为准。
- 常见执行方式是用 `psql "$DATABASE_URL" -f migrations/<file>.sql`。

## 验证
- 检查迁移顺序是否正确。
- 核对后端是否需要同步更新 schema、查询或测试。
