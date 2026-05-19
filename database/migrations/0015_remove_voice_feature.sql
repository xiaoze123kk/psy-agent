BEGIN;

DROP TABLE IF EXISTS voice_sessions;

ALTER TABLE IF EXISTS user_settings
    DROP COLUMN IF EXISTS voice_enabled,
    DROP COLUMN IF EXISTS save_voice_audio,
    DROP COLUMN IF EXISTS save_transcript;

UPDATE messages
SET input_type = 'text'
WHERE input_type = 'voice';

ALTER TABLE IF EXISTS messages
    DROP CONSTRAINT IF EXISTS messages_input_type_check;

ALTER TABLE IF EXISTS messages
    ADD CONSTRAINT messages_input_type_check
    CHECK (input_type IN ('text', 'test', 'system'));

COMMIT;
