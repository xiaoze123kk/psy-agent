# Database

SQL-first migration scaffold for PostgreSQL.

## Initial Migration

Create local database once:

```bash
createdb -h 127.0.0.1 -p 5432 -U postgres psychology_agent
```

Run the first migration against your database:

```bash
psql "$DATABASE_URL" -f migrations/0001_init.sql
psql "$DATABASE_URL" -f migrations/0002_refresh_tokens.sql
psql "$DATABASE_URL" -f migrations/0003_username_auth.sql
psql "$DATABASE_URL" -f migrations/0004_knowledge.sql
psql "$DATABASE_URL" -f migrations/0005_knowledge_beta.sql
psql "$DATABASE_URL" -f migrations/0007_counseling_corpus_milvus.sql
```

Local PostgreSQL example:

```bash
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0001_init.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0002_refresh_tokens.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0003_username_auth.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0004_knowledge.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0005_knowledge_beta.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0007_counseling_corpus_milvus.sql
```

## Notes

- Uses `pgcrypto` for UUID generation (`gen_random_uuid()`).
- Milvus is used for rebuildable knowledge and counseling example vector indexes.
- PostgreSQL remains the source of truth for article/chunk text, source metadata, licensing, and review state.
- Tables are designed around chat continuity, safety routing, and memory control.
