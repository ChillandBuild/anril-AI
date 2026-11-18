-- Undo 291: every reply goes back to companions.model.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions DROP COLUMN IF EXISTS small_talk_model;
