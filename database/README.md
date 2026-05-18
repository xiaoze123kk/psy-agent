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
psql "$DATABASE_URL" -f migrations/0006_privacy.sql
psql "$DATABASE_URL" -f migrations/0007_counseling_corpus_milvus.sql
psql "$DATABASE_URL" -f migrations/0008_app_runtime_schema_alignment.sql
psql "$DATABASE_URL" -f migrations/0009_memory_system.sql
psql "$DATABASE_URL" -f migrations/0010_chat_turn_idempotency.sql
psql "$DATABASE_URL" -f migrations/0011_conversation_turn_traces.sql
psql "$DATABASE_URL" -f migrations/0012_pending_memory_jobs.sql
psql "$DATABASE_URL" -f migrations/0013_companion_styles.sql
psql "$DATABASE_URL" -f migrations/0014_conversation_session_digest.sql
psql "$DATABASE_URL" -f migrations/0015_remove_voice_feature.sql
```

Local PostgreSQL example:

```bash
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0001_init.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0002_refresh_tokens.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0003_username_auth.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0004_knowledge.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0005_knowledge_beta.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0006_privacy.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0007_counseling_corpus_milvus.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0008_app_runtime_schema_alignment.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0009_memory_system.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0010_chat_turn_idempotency.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0011_conversation_turn_traces.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0012_pending_memory_jobs.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0013_companion_styles.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0014_conversation_session_digest.sql
psql "postgresql://postgres:123456@127.0.0.1:5432/psychology_agent" -f migrations/0015_remove_voice_feature.sql
```

## Notes

- Uses `pgcrypto` for UUID generation (`gen_random_uuid()`).
- Milvus is used for rebuildable knowledge and counseling example vector indexes.
- PostgreSQL remains the source of truth for article/chunk text, source metadata, licensing, and review state.
- Tables are designed around chat continuity, safety routing, and memory control.
- `0008_app_runtime_schema_alignment.sql` aligns the SQL-first schema with the current app runtime tables for tests and user feedback.
- `0013_companion_styles.sql` moves multi-style companion preferences into account-level storage and seeds existing `user_settings.companion_style` values as the selected style.
- `0014_conversation_session_digest.sql` adds persisted conversation-level digest fields for continuity.
- `0015_remove_voice_feature.sql` removes the retired voice feature tables, columns, and message input type.
