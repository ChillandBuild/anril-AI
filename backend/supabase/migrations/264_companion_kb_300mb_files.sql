-- 264: the knowledge-base bucket takes files up to 300 MB (was 50 MB, set in 257).
--
-- Example: AstroTamil's scanned book "சாதக அலங்காரம்.pdf" is 227 MB. Before this, storage refused it at
-- the upload link. After this, the browser uploads it and the reading job reads it page by page.
--
-- Order matters:
--   1. Supabase Pro plan, then Storage > Settings > global file size limit >= 300 MB. A bucket limit
--      above the global limit does not let a bigger file in; the global limit still wins.
--   2. Apply this migration.
--   3. Deploy the backend whose filetypes.MAX_BYTES is 300 MB (it hands out the upload links).
-- Keep this number equal to MAX_BYTES in app/companion/kb/filetypes.py.
UPDATE storage.buckets
SET file_size_limit = 314572800          -- 300 * 1024 * 1024
WHERE id = 'companion-kb-documents';
