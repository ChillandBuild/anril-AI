-- Undo 284: back to the 3 best-judged pieces of the main resource.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions DROP COLUMN IF EXISTS full_main_resource;
