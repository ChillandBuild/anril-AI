-- Undo 320_reports_customers_forms.sql. Drops every tag and feedback row.
SET LOCAL lock_timeout = '5s';

DROP FUNCTION IF EXISTS public.analytics_response_times_split(uuid, timestamptz, timestamptz);

ALTER TABLE public.meta_lead_forms DROP COLUMN IF EXISTS auto_hello;
DROP INDEX IF EXISTS public.idx_meta_form_leads_template_msg;
ALTER TABLE public.meta_form_leads
  DROP COLUMN IF EXISTS sent_to_calling_at,
  DROP COLUMN IF EXISTS delivery_updated_at,
  DROP COLUMN IF EXISTS delivery_status;

ALTER TABLE public.reengagement_steps DROP COLUMN IF EXISTS target_group_id;

DROP TABLE IF EXISTS public.customer_feedback;
DROP TABLE IF EXISTS public.lead_tags;
