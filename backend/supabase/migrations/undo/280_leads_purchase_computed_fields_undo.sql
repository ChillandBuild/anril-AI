-- Undo 280_leads_purchase_computed_fields.sql
DROP FUNCTION IF EXISTS last_purchase_at(leads);
DROP FUNCTION IF EXISTS won_deal_count(leads);
