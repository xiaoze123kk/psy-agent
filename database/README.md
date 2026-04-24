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
```

Local PostgreSQL example:

```bash
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0001_init.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0002_refresh_tokens.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0003_username_auth.sql
```

## Notes

- Uses `pgcrypto` for UUID generation (`gen_random_uuid()`).
- If `pgvector` is installed, `memory_embeddings.embedding` uses `vector(1536)`.
- If `pgvector` is not installed, `memory_embeddings.embedding` falls back to `DOUBLE PRECISION[]`.
- Tables are designed around chat continuity, safety routing, and memory control.
