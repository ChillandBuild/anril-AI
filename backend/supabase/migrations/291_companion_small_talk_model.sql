-- 291_companion_small_talk_model.sql
-- A character can answer greetings and chit-chat on a cheaper model than its real answers
-- (AstroTamil review 2026-11-17: predictions on Gemini 3.8 Flash, "வணக்கம்" on 3.5 Flash Lite).
-- The question step already says when no file is needed (kb needs_docs = false); that reply uses
-- small_talk_model. NULL = every reply uses companions.model, exactly as before.
-- Additive: one nullable column. Apply BEFORE the code deploy (the character form saves it).
-- Undo: undo/291_companion_small_talk_model_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions ADD COLUMN IF NOT EXISTS small_talk_model text;

COMMENT ON COLUMN public.companions.small_talk_model IS
  'Model for replies the question step marks as small talk (no file needed). NULL = use model.';
