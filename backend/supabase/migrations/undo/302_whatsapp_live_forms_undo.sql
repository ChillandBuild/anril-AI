-- Undo 302.
DROP TABLE IF EXISTS whatsapp_form_bookings;
DROP TABLE IF EXISTS whatsapp_flow_keys;
ALTER TABLE whatsapp_form_designs DROP COLUMN IF EXISTS settings;
ALTER TABLE whatsapp_form_designs DROP COLUMN IF EXISTS kind;
