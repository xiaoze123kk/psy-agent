BEGIN;

CREATE TABLE IF NOT EXISTS knowledge_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(120) NOT NULL UNIQUE,
    title VARCHAR(160) NOT NULL,
    category VARCHAR(32) NOT NULL,
    audience VARCHAR(16) NOT NULL DEFAULT 'all' CHECK (
        audience IN ('all', 'teen', 'adult')
    ),
    summary_30s TEXT NOT NULL,
    explanation_3min TEXT NOT NULL,
    advanced_text TEXT,
    common_misunderstandings JSONB NOT NULL DEFAULT '[]'::jsonb,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    seek_help_when JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'published' CHECK (
        status IN ('draft', 'published', 'archived')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_articles_category ON knowledge_articles (category);

CREATE INDEX IF NOT EXISTS idx_knowledge_articles_audience ON knowledge_articles (audience);

CREATE INDEX IF NOT EXISTS idx_knowledge_articles_status_updated ON knowledge_articles (status, updated_at DESC);

COMMIT;
