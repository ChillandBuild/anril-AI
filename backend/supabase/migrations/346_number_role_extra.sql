-- 346_number_role_extra.sql  (v9.2 WhatsApp > Numbers: the "Extra" role)
-- An Extra number is connected and replies to whoever writes to it, but it never sends Reach
-- campaigns and never takes over when the Main number stops (only Standby numbers do).
-- Changes only the allowed values of phone_numbers.role; no row changes.
-- Undo: undo/346_number_role_extra_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_role_check;
ALTER TABLE public.phone_numbers ADD CONSTRAINT phone_numbers_role_check
  CHECK (role IN ('primary', 'standby', 'extra', 'archived'));
