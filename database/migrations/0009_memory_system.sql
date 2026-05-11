BEGIN;

ALTER TABLE IF EXISTS user_memories
    ADD COLUMN IF NOT EXISTS title VARCHAR(120),
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_id UUID REFERENCES user_memories (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS review_state VARCHAR(24) NOT NULL DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_user_memories_user_type_status
    ON user_memories (user_id, memory_type, status);

CREATE INDEX IF NOT EXISTS idx_user_memories_user_review
    ON user_memories (user_id, review_state);

CREATE TABLE IF NOT EXISTS memory_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    memory_id UUID REFERENCES user_memories (id) ON DELETE SET NULL,
    action VARCHAR(32) NOT NULL,
    before_value JSONB,
    after_value JSONB,
    reason TEXT,
    actor VARCHAR(32) NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_operations_user_created_at
    ON memory_operations (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_operations_memory_created_at
    ON memory_operations (memory_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL DEFAULT 'running',
    trigger VARCHAR(24) NOT NULL DEFAULT 'manual',
    sessions_reviewed INTEGER NOT NULL DEFAULT 0,
    memories_touched INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_memory_consolidation_runs_user_started
    ON memory_consolidation_runs (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_consolidation_runs_status
    ON memory_consolidation_runs (status);

ALTER TABLE IF EXISTS memory_embeddings
    ADD COLUMN IF NOT EXISTS embedding_key VARCHAR(256) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user_memory
    ON memory_embeddings (user_id, memory_id);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_key
    ON memory_embeddings (embedding_key);

COMMIT;
