-- Undo 318: no chart guard (birth details reach the model again; replies are not checked).
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions DROP COLUMN IF EXISTS chart_guard;
