-- Undo 281_leads_opted_out_source.sql
ALTER TABLE leads DROP COLUMN IF EXISTS opted_out_by;
ALTER TABLE leads DROP COLUMN IF EXISTS opted_out_detail;
ALTER TABLE leads DROP COLUMN IF EXISTS opted_out_source;
