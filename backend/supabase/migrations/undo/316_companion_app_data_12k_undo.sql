-- Undo 316: back to the 4,000 cap. Fails if a test person's sample is now longer: shorten or clear it first.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users
  DROP CONSTRAINT IF EXISTS companion_end_users_test_app_data_check;

ALTER TABLE public.companion_end_users
  ADD CONSTRAINT companion_end_users_test_app_data_check CHECK (
    test_app_data IS NULL
    OR (char_length(test_app_data) BETWEEN 1 AND 4000 AND external_user_id LIKE 'owner-test:%')
  );
