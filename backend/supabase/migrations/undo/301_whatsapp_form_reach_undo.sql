-- Undo 301.
DROP TABLE IF EXISTS whatsapp_form_sends;
ALTER TABLE whatsapp_form_designs DROP COLUMN IF EXISTS triggers;
