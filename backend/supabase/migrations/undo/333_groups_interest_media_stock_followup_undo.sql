-- Undo 333. Steps of the new kind must go before the old constraint can come back.
DELETE FROM reengagement_steps WHERE type = 'campaign_reply';
ALTER TABLE reengagement_steps DROP CONSTRAINT IF EXISTS reengagement_steps_type_check;
ALTER TABLE reengagement_steps ADD CONSTRAINT reengagement_steps_type_check CHECK (type IN ('broadcast', 'inbound'));
ALTER TABLE stock_movements DROP COLUMN IF EXISTS photo_path;
ALTER TABLE catalog_media DROP COLUMN IF EXISTS colour;
ALTER TABLE leads DROP COLUMN IF EXISTS interested_item_ids;
DROP FUNCTION IF EXISTS total_spent_paise(leads);
