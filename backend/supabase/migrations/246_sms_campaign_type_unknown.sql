-- 246_sms_campaign_type_unknown.sql
-- The template category (Service Implicit vs Service Explicit / Promo) is fixed by DLT approval and
-- applied by Bulk9; Anril no longer asks the client to classify. A campaign whose template category
-- Bulk9 did not report, or a "Type my own" (route=dlt_manual) send, records 'unknown'.
-- Applied live 2026-11-05 via Supabase MCP.

ALTER TABLE sms_campaigns DROP CONSTRAINT IF EXISTS sms_campaigns_template_type_check;
ALTER TABLE sms_campaigns ADD CONSTRAINT sms_campaigns_template_type_check
  CHECK (template_type = ANY (ARRAY['service'::text, 'promotional'::text, 'unknown'::text]));
