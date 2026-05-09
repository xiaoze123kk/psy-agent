BEGIN;

CREATE TABLE IF NOT EXISTS conversation_turn_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL REFERENCES conversation_turns (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES conversation_threads (id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    trace_type VARCHAR(32) NOT NULL DEFAULT 'graph_node',
    node_name VARCHAR(80) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'completed',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_turn_traces_turn_sequence
    ON conversation_turn_traces (turn_id, sequence);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_traces_turn
    ON conversation_turn_traces (turn_id);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_traces_thread_created
    ON conversation_turn_traces (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_traces_node_status
    ON conversation_turn_traces (node_name, status);

COMMIT;
