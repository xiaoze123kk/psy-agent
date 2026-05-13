BEGIN;

ALTER TABLE conversation_threads
    ADD COLUMN IF NOT EXISTS session_digest JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMIT;

