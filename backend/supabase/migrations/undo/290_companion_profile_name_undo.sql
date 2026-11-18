-- Undo 290: drops the profile name. Rows with "~" in external_user_id stay (they are ordinary people rows).
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users DROP COLUMN IF EXISTS profile_name;
