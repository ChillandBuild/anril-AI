-- 293_companion_working_step.sql
-- A character can think in a hidden <working> block before it replies (AstroTamil review 2026-11-17:
-- "the AI first writes its working inside the system, then the user reply"). The block is cut off by
-- code before the reply is shown or saved (prompt.split_working); the Playground shows it. Not for
-- small talk. The reply cap rises from 700 to 3,000 tokens for such a character. Default false = as before.
-- Additive. Apply BEFORE the code deploy (the character form saves it).
-- Undo: undo/293_companion_working_step_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions ADD COLUMN IF NOT EXISTS working_step boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.companions.working_step IS
  'Think in a hidden <working> block before replying (cut off before it is shown or saved). Not for small talk.';
