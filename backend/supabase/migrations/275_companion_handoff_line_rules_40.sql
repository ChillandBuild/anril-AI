-- 275_companion_handoff_line_rules_40.sql
-- Owner's decision 2026-11-17: nothing domain-specific is fixed in code.
--   1. handoff_line: what a Strict character says instead of an answer that came from no file, written by
--      the business on the Knowledge tab (e.g. Jothidar AI: "இதற்கு நம் ஜோதிடரிடம் கேட்பது நல்லது.").
--      NULL = the generic line in the character's language (engine.HANDOFF_LINES).
--   2. Persona rules limit 30 -> 40: the astrology rules (no death predictions, low-cost remedies) moved
--      out of code into each character's own editable rules, so they need room.
-- Safe before or after the code deploy: old code never reads handoff_line, and 40 only loosens the check.
-- Undo: undo/275_companion_handoff_line_rules_40_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions
  ADD COLUMN IF NOT EXISTS handoff_line text
  CONSTRAINT companions_handoff_line_check CHECK (handoff_line IS NULL OR char_length(handoff_line) BETWEEN 1 AND 300);

ALTER TABLE public.companions DROP CONSTRAINT IF EXISTS companions_rules_check;
ALTER TABLE public.companions ADD CONSTRAINT companions_rules_check CHECK (cardinality(rules) <= 40);
