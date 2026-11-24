-- Undo 348_number_role_extra_removed.sql: allow the Extra role again (no row changes).
ALTER TABLE public.phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_role_check;
ALTER TABLE public.phone_numbers ADD CONSTRAINT phone_numbers_role_check
  CHECK (role IN ('primary', 'standby', 'extra', 'archived'));
