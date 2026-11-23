-- Undo 346_number_role_extra.sql. Extra numbers go back to standby first, so the old check holds.
UPDATE public.phone_numbers SET role = 'standby' WHERE role = 'extra';
ALTER TABLE public.phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_role_check;
ALTER TABLE public.phone_numbers ADD CONSTRAINT phone_numbers_role_check
  CHECK (role IN ('primary', 'standby', 'archived'));
