-- Undo 282_leads_reply_computed_fields.sql
DROP FUNCTION IF EXISTS last_message(leads);
DROP FUNCTION IF EXISTS waiting_since(leads);
