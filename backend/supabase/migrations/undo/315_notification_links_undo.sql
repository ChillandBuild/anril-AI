-- Undo 315: drop the alert link column.
ALTER TABLE public.app_notifications DROP COLUMN IF EXISTS url;
