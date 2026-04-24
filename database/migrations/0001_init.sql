BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(32) UNIQUE,
    password_hash TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    nickname VARCHAR(80) NOT NULL,
    age_range VARCHAR(32) NOT NULL,
    user_mode VARCHAR(16) NOT NULL CHECK (user_mode IN ('teen', 'adult')),
    usage_goals JSONB NOT NULL DEFAULT '[]'::jsonb,
    onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    memory_mode VARCHAR(24) NOT NULL DEFAULT 'summary_only' CHECK (memory_mode IN ('off', 'summary_only', 'long_term')),
    companion_style VARCHAR(32) NOT NULL DEFAULT 'gentle',
    voice_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    save_voice_audio BOOLEAN NOT NULL DEFAULT FALSE,
    save_transcript BOOLEAN NOT NULL DEFAULT TRUE,
    crisis_resource_region VARCHAR(12) NOT NULL DEFAULT 'CN',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    langgraph_thread_id VARCHAR(128) NOT NULL UNIQUE,
    title VARCHAR(120),
    mode VARCHAR(32) NOT NULL DEFAULT 'companion',
    last_summary TEXT,
    last_risk_level VARCHAR(8) NOT NULL DEFAULT 'L0' CHECK (last_risk_level IN ('L0', 'L1', 'L2', 'L3')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    input_type VARCHAR(16) NOT NULL DEFAULT 'text' CHECK (input_type IN ('text', 'voice', 'test', 'system')),
    risk_level VARCHAR(8) CHECK (risk_level IN ('L0', 'L1', 'L2', 'L3')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    structured_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    importance INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.500 CHECK (confidence BETWEEN 0 AND 1),
    source_thread_id UUID REFERENCES conversation_threads(id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    visibility VARCHAR(24) NOT NULL DEFAULT 'user_visible' CHECK (visibility IN ('user_visible', 'internal_safety')),
    status VARCHAR(24) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted', 'expired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id UUID NOT NULL REFERENCES user_memories(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    embedding vector(1536),
    embedding_model VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mood_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mood_score INTEGER NOT NULL CHECK (mood_score BETWEEN 1 AND 5),
    anxiety_score INTEGER CHECK (anxiety_score BETWEEN 1 AND 5),
    energy_score INTEGER CHECK (energy_score BETWEEN 1 AND 5),
    sleep_quality INTEGER CHECK (sleep_quality BETWEEN 1 AND 5),
    mood_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT,
    source VARCHAR(24) NOT NULL DEFAULT 'checkin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    risk_level VARCHAR(8) NOT NULL CHECK (risk_level IN ('L2', 'L3')),
    trigger_text TEXT NOT NULL,
    safety_action_taken JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(120) NOT NULL,
    test_type VARCHAR(24) NOT NULL CHECK (test_type IN ('state', 'personality', 'anime')),
    version VARCHAR(32) NOT NULL DEFAULT 'v1',
    estimated_minutes INTEGER NOT NULL DEFAULT 5,
    audience VARCHAR(16) NOT NULL DEFAULT 'all',
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS test_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    test_id UUID NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    raw_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_code VARCHAR(64),
    result_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_threads_user_updated_at
    ON conversation_threads (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_thread_created_at
    ON messages (thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_user_created_at
    ON messages (user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memories_user_status_updated
    ON user_memories (user_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mood_logs_user_created_at
    ON mood_logs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_risk_events_user_created_at
    ON risk_events (user_id, created_at DESC);

COMMIT;
