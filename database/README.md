# Database

SQL-first migration scaffold for PostgreSQL.

## Initial Migration

Run the first migration against your database:

```bash
psql "$DATABASE_URL" -f migrations/0001_init.sql
```

## Notes

- Uses `pgcrypto` for UUID generation (`gen_random_uuid()`).
- Uses `vector` extension for memory embeddings.
- Tables are designed around chat continuity, safety routing, and memory control.
