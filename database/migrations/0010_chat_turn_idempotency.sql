BEGIN;

CREATE TABLE IF NOT EXISTS conversation_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES conversation_threads (id) ON DELETE CASCADE,
    client_message_id VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    turn_status VARCHAR(16) NOT NULL DEFAULT 'running' CHECK (
        turn_status IN ('accepted', 'running', 'completed', 'failed')
    ),
    delivery_status VARCHAR(32),
    failure_reason TEXT,
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    user_message_id UUID REFERENCES messages (id) ON DELETE SET NULL,
    assistant_message_id UUID REFERENCES messages (id) ON DELETE SET NULL,
    response_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_turns_client_message
    ON conversation_turns (user_id, thread_id, client_message_id);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_thread_created
    ON conversation_turns (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_status_updated
    ON conversation_turns (turn_status, updated_at);

COMMIT;
