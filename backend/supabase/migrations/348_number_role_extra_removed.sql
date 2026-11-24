-- 348_number_role_extra_removed.sql  (WhatsApp > Numbers: the "Extra" role is gone)
-- The owner asked to drop Extra (added in 346) and instead pick a number per job for staff alerts,
-- OTP codes and Reach campaigns (app_settings sender_for_<job>, services/number_jobs.py).
-- Any Extra number becomes Standby first (none existed live on 2026-11-24), then the role check
-- goes back to Main / Standby / Archived.
-- Undo: undo/348_number_role_extra_removed_undo.sql
SET LOCAL lock_timeout = '5s';
UPDATE public.phone_numbers SET role = 'standby' WHERE role = 'extra';
ALTER TABLE public.phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_role_check;
ALTER TABLE public.phone_numbers ADD CONSTRAINT phone_numbers_role_check
  CHECK (role IN ('primary', 'standby', 'archived'));
