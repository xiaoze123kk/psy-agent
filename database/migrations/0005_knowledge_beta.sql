BEGIN;

CREATE TABLE IF NOT EXISTS knowledge_sources (
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

ALTER TABLE knowledge_articles
    ADD COLUMN IF NOT EXISTS source_id UUID REFERENCES knowledge_sources (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(24) NOT NULL DEFAULT 'published',
    ADD COLUMN IF NOT EXISTS license VARCHAR(120),
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS reviewer_note TEXT,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_knowledge_articles_source_id ON knowledge_articles (source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_review_status ON knowledge_articles (review_status);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES knowledge_articles (id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    title VARCHAR(180) NOT NULL,
    content TEXT NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    token_count INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    license VARCHAR(120),
    status VARCHAR(16) NOT NULL DEFAULT 'published',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_knowledge_chunks_article_index UNIQUE (article_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_article_id ON knowledge_chunks (article_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_status_updated ON knowledge_chunks (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    category VARCHAR(32),
    audience VARCHAR(16),
    coverage_status VARCHAR(24) NOT NULL DEFAULT 'insufficient',
    confidence VARCHAR(16) NOT NULL DEFAULT 'low',
    top_score INTEGER NOT NULL DEFAULT 0,
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    hit_count INTEGER NOT NULL DEFAULT 1,
    thread_id VARCHAR(128),
    resolved_article_id UUID REFERENCES knowledge_articles (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_normalized_question ON knowledge_gaps (normalized_question);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_status ON knowledge_gaps (status);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_category ON knowledge_gaps (category);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_audience ON knowledge_gaps (audience);

COMMIT;
