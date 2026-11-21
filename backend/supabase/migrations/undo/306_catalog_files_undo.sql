-- Undo 306 (the stored files stay in the catalog-media bucket under <tenant>/files/; remove them there if wanted).
DROP FUNCTION IF EXISTS record_catalog_file_send(uuid, uuid, uuid);
DROP TABLE IF EXISTS catalog_file_sends;
DROP TABLE IF EXISTS catalog_files;
