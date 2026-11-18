-- 282_companion_profile_name.sql
-- One app user can ask about more than one profile (AstroTamil: Vivek asks about his own chart, his
-- brother Karthik's and his sister Priya's). The app sends profile_id + profile_name with each message.
-- Each (user, profile) becomes its own person row, so memory, history and mood never mix between charts:
--   external_user_id = "<user_id>~<profile_id>", e.g. "u42~p7". A real user id can never contain "~"
--   (keys.USER_ID_RE), so this can't collide with another user. No profile_id -> "u42", exactly as before.
-- profile_name ("Karthik") is the profile's display name: the prompt says whose profile this is, and the
-- dashboard shows it next to the user's name. NULL when the app sends none.
-- Additive: one nullable column. Apply BEFORE the code deploy (the code writes this column).
-- Undo: undo/282_companion_profile_name_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companion_end_users
  ADD COLUMN IF NOT EXISTS profile_name text
  CONSTRAINT companion_end_users_profile_name_check CHECK (char_length(profile_name) BETWEEN 1 AND 100);

COMMENT ON COLUMN public.companion_end_users.profile_name IS
  'Whose profile this person row is about (e.g. the chart''s owner "Karthik"), as the app last sent it. NULL = none sent.';
