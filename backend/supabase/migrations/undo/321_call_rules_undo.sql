-- Undo 321_call_rules.sql. Drops every per-person calling mode and leave date. The business rules
-- in app_settings ('call_rules') are left alone: nothing reads them once the code is rolled back.
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.callers DROP CONSTRAINT IF EXISTS callers_leave_dates_check;
ALTER TABLE public.callers DROP CONSTRAINT IF EXISTS callers_calling_mode_check;
ALTER TABLE public.callers
  DROP COLUMN IF EXISTS break_alert_sent_at,
  DROP COLUMN IF EXISTS leave_leads_moved_at,
  DROP COLUMN IF EXISTS leave_reason,
  DROP COLUMN IF EXISTS leave_to,
  DROP COLUMN IF EXISTS leave_from,
  DROP COLUMN IF EXISTS calling_mode;
