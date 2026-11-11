-- Undo for 257_companion_kb_library.sql. NOT a migration: run by hand in the Supabase SQL Editor,
-- only if 257 must be taken back. Deletes every Anril Agents book, page and passage row.
-- Run the undo files in reverse order (260, 259, 258, then this one).
-- The stored files are not removed by SQL: empty the bucket companion-kb-documents in the
-- dashboard (Storage) first, then the last statement removes the bucket row.

ALTER TABLE companions DROP COLUMN IF EXISTS knowledge_collection_id;
DROP TABLE IF EXISTS companion_kb_chunk_questions;
DROP TABLE IF EXISTS companion_kb_chunks;
DROP TABLE IF EXISTS companion_kb_pages;
DROP TABLE IF EXISTS companion_kb_documents;
DROP TABLE IF EXISTS companion_kb_collections;
DELETE FROM storage.buckets WHERE id = 'companion-kb-documents';
