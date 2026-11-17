-- Undo of 275_companion_handoff_line_rules_40.sql.
-- The 30-rule check fails while any character has more than 30 rules: trim those first
--   (SELECT id, name, cardinality(rules) FROM companions WHERE cardinality(rules) > 30;).
-- Dropping handoff_line loses every business's own handoff line; Strict falls back to the generic one.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions DROP CONSTRAINT IF EXISTS companions_rules_check;
ALTER TABLE public.companions ADD CONSTRAINT companions_rules_check CHECK (cardinality(rules) <= 30);

ALTER TABLE public.companions DROP COLUMN IF EXISTS handoff_line;
