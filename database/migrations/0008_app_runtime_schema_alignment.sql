BEGIN;

-- The app now keeps test definitions in code, so attempts store the stable
-- test id such as state-check-v1 instead of referencing rows in tests.id.
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    IF to_regclass('public.test_attempts') IS NOT NULL THEN
        FOR fk_name IN
            SELECT DISTINCT c.conname
            FROM pg_constraint c
            JOIN pg_attribute a
                ON a.attrelid = c.conrelid
                AND a.attnum = ANY(c.conkey)
            WHERE c.conrelid = 'public.test_attempts'::regclass
                AND c.contype = 'f'
                AND a.attname = 'test_id'
        LOOP
            EXECUTE format('ALTER TABLE test_attempts DROP CONSTRAINT %I', fk_name);
        END LOOP;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public.test_attempts') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE test_attempts ALTER COLUMN test_id TYPE VARCHAR(64) USING test_id::text';
    END IF;
END
$$;

ALTER TABLE IF EXISTS test_attempts
    ADD COLUMN IF NOT EXISTS answers JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS result_label VARCHAR(80);

CREATE INDEX IF NOT EXISTS idx_test_attempts_user_created_at
    ON test_attempts (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_test_attempts_test_id
    ON test_attempts (test_id);

CREATE TABLE IF NOT EXISTS test_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    attempt_id UUID NOT NULL REFERENCES test_attempts (id) ON DELETE CASCADE,
    test_id VARCHAR(64) NOT NULL,
    test_title VARCHAR(160) NOT NULL,
    result_code VARCHAR(32) NOT NULL,
    result_label VARCHAR(80) NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_test_history_user_completed_at
    ON test_history (user_id, completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_test_history_attempt_id
    ON test_history (attempt_id);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    thread_id UUID REFERENCES conversation_threads (id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    mode VARCHAR(20) NOT NULL DEFAULT 'companion',
    save_transcript BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_user_created_at
    ON voice_sessions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_thread_id
    ON voice_sessions (thread_id);

CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    target_type VARCHAR(30) NOT NULL,
    target_id VARCHAR(100),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user_created_at
    ON user_feedback (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_feedback_target
    ON user_feedback (target_type, target_id);

COMMIT;
