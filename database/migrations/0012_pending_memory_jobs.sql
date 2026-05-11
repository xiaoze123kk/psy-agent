BEGIN;

CREATE TABLE IF NOT EXISTS pending_memory_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES conversation_threads (id) ON DELETE CASCADE,
    turn_id UUID NOT NULL REFERENCES conversation_turns (id) ON DELETE CASCADE,
    assistant_message_id UUID REFERENCES messages (id) ON DELETE SET NULL,
    job_type VARCHAR(32) NOT NULL DEFAULT 'memory_write',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ,
    locked_by VARCHAR(80),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_memory_jobs_turn_type
    ON pending_memory_jobs (turn_id, job_type);

CREATE INDEX IF NOT EXISTS idx_pending_memory_jobs_status_next_run
    ON pending_memory_jobs (status, next_run_at);

CREATE INDEX IF NOT EXISTS idx_pending_memory_jobs_turn
    ON pending_memory_jobs (turn_id);

CREATE INDEX IF NOT EXISTS idx_pending_memory_jobs_thread_created
    ON pending_memory_jobs (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_pending_memory_jobs_assistant_message
    ON pending_memory_jobs (assistant_message_id);

COMMIT;
