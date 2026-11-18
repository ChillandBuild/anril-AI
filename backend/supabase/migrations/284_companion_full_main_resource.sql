-- 284_companion_full_main_resource.sql
-- A character can send its main resource (the tier-1 book of its collection) whole with every question
-- that needs the books, instead of the 3 best-judged pieces of it. AstroTamil review 2026-11-17: the
-- 29-page Rule Book (28,590 characters, no headings inside) holds the steps for every topic, and replies
-- were answering from "own reasoning, 0 pages". Over 40,000 characters the normal search runs instead
-- (kb/search.MAX_WHOLE_MAIN_CHARS). Small talk still searches nothing. Default false = as before.
-- Additive. Apply BEFORE the code deploy (the character form saves it).
-- Undo: undo/284_companion_full_main_resource_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions ADD COLUMN IF NOT EXISTS full_main_resource boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.companions.full_main_resource IS
  'Send the main resource whole (up to 40,000 characters) with every question that needs the books.';
