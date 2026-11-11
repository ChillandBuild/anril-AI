-- 259_companion_kb_reply.sql
-- Anril Agents knowledge base, part 3: the reply says where its answer came from.
--
-- - companions.own_reasoning: true (default, how characters behave today) = when no book answers,
--   the character may answer from its own reasoning and says so. false = "documents only".
-- - companion_messages.basis: 'primary' (main resource) | 'book' | 'own' | 'chat'. NULL on old rows
--   and on user messages.
-- - companion_messages.sources: a small snapshot of the passages the reply relied on, e.g.
--     [{"document": "Book 7", "page_from": 212, "page_to": 212, "chunk_id": "…", "document_id": "…"}]
--   A snapshot, not ids alone: if Book 7 is deleted next month, the old reply still shows
--   "Book 7, p. 212".
--   A reply that pauses for an app tool keeps its supplied passages inside the pending turn's
--   existing state (companion_pending_turns.messages), so no column is needed for that.
--
-- Add-only: three nullable / defaulted columns on existing companion tables. Existing rows keep
-- working with empty values. Undo: migrations/undo/259_companion_kb_reply_undo.sql

SET LOCAL lock_timeout = '5s';

ALTER TABLE companions
  ADD COLUMN IF NOT EXISTS own_reasoning boolean NOT NULL DEFAULT true;

ALTER TABLE companion_messages
  ADD COLUMN IF NOT EXISTS basis text CHECK (basis IS NULL OR basis IN ('primary', 'book', 'own', 'chat')),
  ADD COLUMN IF NOT EXISTS sources jsonb;
