BEGIN;

CREATE TABLE IF NOT EXISTS companion_styles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title VARCHAR(80) NOT NULL,
    definition TEXT NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companion_styles_user_updated_at
    ON companion_styles (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_companion_styles_user_default
    ON companion_styles (user_id, is_default);

CREATE UNIQUE INDEX IF NOT EXISTS uq_companion_styles_one_default_per_user
    ON companion_styles (user_id)
    WHERE is_default;

INSERT INTO companion_styles (
    id,
    user_id,
    title,
    definition,
    is_default,
    sort_order,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    user_settings.user_id,
    '当前风格',
    LEFT(BTRIM(user_settings.companion_style), 500),
    TRUE,
    0,
    NOW(),
    NOW()
FROM user_settings
WHERE user_settings.companion_style IS NOT NULL
    AND BTRIM(user_settings.companion_style) <> ''
    AND user_settings.companion_style NOT IN ('gentle', 'rational', 'reflective', 'action')
    AND NOT EXISTS (
        SELECT 1
        FROM companion_styles
        WHERE companion_styles.user_id = user_settings.user_id
    );

COMMIT;
