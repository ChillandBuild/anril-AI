-- Undo 314: everyone works at all places again; bills go back to taking from the bill place first.
ALTER TABLE deals DROP COLUMN IF EXISTS place_id;
ALTER TABLE tenant_users DROP COLUMN IF EXISTS place_id;
