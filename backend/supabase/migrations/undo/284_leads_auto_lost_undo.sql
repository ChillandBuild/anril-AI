-- Undo 284_leads_auto_lost.sql
DROP FUNCTION IF EXISTS public.stopped_replying_leads(timestamptz, integer);
ALTER TABLE leads DROP COLUMN IF EXISTS auto_lost_dismissed_at;
ALTER TABLE leads DROP COLUMN IF EXISTS lost_auto;
