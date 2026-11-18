-- Undo 285: replies go back to one step, no hidden working.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions DROP COLUMN IF EXISTS working_step;
