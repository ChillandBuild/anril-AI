-- Undo for 259_companion_kb_reply.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Loses the basis / sources labels saved on replies since 259 was applied.
ALTER TABLE companion_messages DROP COLUMN IF EXISTS sources, DROP COLUMN IF EXISTS basis;
ALTER TABLE companions DROP COLUMN IF EXISTS own_reasoning;
