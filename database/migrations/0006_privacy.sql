BEGIN;

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS save_transcript BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS privacy_action_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    action VARCHAR(32) NOT NULL,
    scope VARCHAR(32) NOT NULL,
    affected_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_privacy_action_logs_user_created_at
    ON privacy_action_logs (user_id, created_at DESC);

COMMIT;
