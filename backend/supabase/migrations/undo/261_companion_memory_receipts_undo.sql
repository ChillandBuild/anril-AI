-- Undo for 261_companion_memory_receipts.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Deletes every saved quote and the record of skipped message ranges. Roll the backend back first:
-- the newer backend writes these columns on every fact it saves.
ALTER TABLE companion_memory_state DROP COLUMN IF EXISTS skipped;
ALTER TABLE companion_memory_facts
  DROP COLUMN IF EXISTS source_message_id,
  DROP COLUMN IF EXISTS quote;
