-- Undo 277: drops the Playground test people's saved sample app data (only test data lives there).
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users DROP COLUMN IF EXISTS test_app_data;
