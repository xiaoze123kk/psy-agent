BEGIN;

CREATE TABLE IF NOT EXISTS counseling_corpus_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key VARCHAR(80) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    base_url TEXT NOT NULL,
    terms_url TEXT,
    license VARCHAR(120) NOT NULL,
    language VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
    is_commercial_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    retrieved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_counseling_corpus_sources_source_key
ON counseling_corpus_sources (source_key);

CREATE TABLE IF NOT EXISTS counseling_example_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES counseling_corpus_sources (id) ON DELETE CASCADE,
    external_id VARCHAR(160) NOT NULL DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    mode VARCHAR(24) NOT NULL DEFAULT 'counseling',
    topic VARCHAR(80),
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    context_text TEXT,
    content TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_url TEXT,
    license VARCHAR(120),
    status VARCHAR(16) NOT NULL DEFAULT 'published',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_counseling_examples_source_external_chunk UNIQUE (source_id, external_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_counseling_examples_source_id
ON counseling_example_chunks (source_id);

CREATE INDEX IF NOT EXISTS idx_counseling_examples_mode_status
ON counseling_example_chunks (mode, status);

CREATE INDEX IF NOT EXISTS idx_counseling_examples_topic_status
ON counseling_example_chunks (topic, status);

CREATE INDEX IF NOT EXISTS idx_counseling_examples_status_updated
ON counseling_example_chunks (status, updated_at DESC);

COMMIT;
