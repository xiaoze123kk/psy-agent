BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40);

UPDATE users
SET username = 'user_' || REPLACE(SUBSTRING(id::text, 1, 8), '-', '')
WHERE username IS NULL OR username = '';

ALTER TABLE users ALTER COLUMN username SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);

COMMIT;
