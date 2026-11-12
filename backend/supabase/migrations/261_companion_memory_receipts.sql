-- 261_companion_memory_receipts.sql
-- Aira Companion Level 2 memory, card engine: receipts for facts, and a record of skipped messages.
--
-- - companion_memory_facts.quote: the person's own words the fact came from ("naan Chennai la
--   irukken" for "Lives in Chennai"). The backend only saves a fact whose quote is found inside one of
--   the PERSON's messages (never the character's). NULL for facts saved before this migration and for
--   facts the owner's tools add by hand.
-- - companion_memory_facts.source_message_id: the companion_messages row the quote was found in.
--   No foreign key on purpose: a chat row may be deleted later and the fact must not block that.
-- - companion_memory_state.skipped: message ranges the card could not read after 3 failed nights:
--     [{"after": ts, "through": ts, "count": n, "tries": n, "since": ts, "dead": true?}]
--   The watermark moves past them so the pair is not blocked, but they stay on record here and the
--   nightly job retries them. NULL = nothing skipped.
--
-- Add-only: three nullable columns, no data change, no new table (RLS of both tables is unchanged).
-- Must be applied BEFORE the backend that writes these columns is deployed.

ALTER TABLE companion_memory_facts
  ADD COLUMN IF NOT EXISTS quote text CHECK (quote IS NULL OR char_length(quote) BETWEEN 1 AND 300),
  ADD COLUMN IF NOT EXISTS source_message_id uuid;

ALTER TABLE companion_memory_state
  ADD COLUMN IF NOT EXISTS skipped jsonb;
