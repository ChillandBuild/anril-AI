-- 277_companion_test_app_data.sql
-- A client's app can send "app_data" with every chat message: what it knows about the person right now
-- (AstroTamil: the logged-in user's chart). It goes into that reply's prompt and is never stored.
--
-- The one exception is the dashboard Playground: an owner types a sample (e.g. a chart for the test
-- customer "Meena") once, and it is sent with every Playground message as Meena. This column keeps that
-- sample. The check makes sure only Playground test people ("owner-test:...") can ever have one, so a real
-- customer's app data can't end up here.
-- Additive: one nullable column. Safe before or after the code deploy. Undo: undo/277_companion_test_app_data_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users
  ADD COLUMN IF NOT EXISTS test_app_data text
  CONSTRAINT companion_end_users_test_app_data_check CHECK (
    test_app_data IS NULL
    OR (char_length(test_app_data) BETWEEN 1 AND 4000 AND external_user_id LIKE 'owner-test:%')
  );

COMMENT ON COLUMN public.companion_end_users.test_app_data IS
  'Playground only: the sample app data an owner set for a test person, sent with each Playground message. NULL for every real customer.';
