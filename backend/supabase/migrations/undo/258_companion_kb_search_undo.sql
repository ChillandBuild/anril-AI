-- Undo for 258_companion_kb_search.sql. NOT a migration: run by hand in the Supabase SQL Editor.
DROP FUNCTION IF EXISTS match_companion_kb_chunks(uuid, uuid, integer, text, vector, vector, text, text, text[], integer);
DROP INDEX IF EXISTS companion_kb_chunks_tsv_idx;
