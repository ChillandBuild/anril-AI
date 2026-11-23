-- 316_companion_app_data_12k.sql
-- A full AstroTamil chart (planets, dasa list, dosham, today's gocharam and this month's readings) is
-- ~6,300 characters, over the 4,000 cap from 277. Raise the Playground sample cap to 12,000 to match
-- models.MAX_APP_DATA_CHARS. Only loosens a check: safe before or after the code deploy.
-- Undo: undo/316_companion_app_data_12k_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users
  DROP CONSTRAINT IF EXISTS companion_end_users_test_app_data_check;

ALTER TABLE public.companion_end_users
  ADD CONSTRAINT companion_end_users_test_app_data_check CHECK (
    test_app_data IS NULL
    OR (char_length(test_app_data) BETWEEN 1 AND 12000 AND external_user_id LIKE 'owner-test:%')
  );
