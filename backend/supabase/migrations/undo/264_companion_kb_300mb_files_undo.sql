-- Undo for 264_companion_kb_300mb_files.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Roll the backend back first (filetypes.MAX_BYTES back to 50 MB), or it hands out upload links that
-- storage then refuses. Files already stored above 50 MB stay where they are and still read.
UPDATE storage.buckets
SET file_size_limit = 52428800           -- 50 * 1024 * 1024
WHERE id = 'companion-kb-documents';
