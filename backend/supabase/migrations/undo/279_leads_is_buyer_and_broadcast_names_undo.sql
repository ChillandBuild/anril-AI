-- Undo 279_leads_is_buyer_and_broadcast_names.sql
DROP FUNCTION IF EXISTS sent_broadcast_names(leads);
DROP TRIGGER IF EXISTS deals_is_buyer_trg ON deals;
DROP FUNCTION IF EXISTS deals_sync_lead_is_buyer();
DROP TRIGGER IF EXISTS leads_is_buyer_trg ON leads;
DROP FUNCTION IF EXISTS leads_set_is_buyer();
DROP FUNCTION IF EXISTS lead_is_buyer(uuid, timestamptz, timestamptz);
DROP INDEX IF EXISTS leads_tenant_buyer_idx;
ALTER TABLE leads DROP COLUMN IF EXISTS is_buyer;
