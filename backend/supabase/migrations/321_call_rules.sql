-- 321_call_rules.sql
-- v9.2 #21 Call IQ rules (batch I-B): per-person SIM or cloud, leave, break alerts.
--
-- Business-wide rules (calling hours, daily limit, break limit, hide numbers) live in app_settings
-- under the key 'call_rules' (JSON), so they need no table. Per-person things live on callers:
--   calling_mode            business_default | sim | cloud   (which way this person calls)
--   leave_from / leave_to   dates (IST) of a leave; both NULL = not on leave
--   leave_reason            optional plain words
--   leave_leads_moved_at    when this leave's open leads were handed to the others (NULL = not yet)
--   break_alert_sent_at     last time the owner was told this person stayed on break too long
--
-- Additive, idempotent. Undo: undo/321_call_rules_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.callers
  ADD COLUMN IF NOT EXISTS calling_mode text NOT NULL DEFAULT 'business_default',
  ADD COLUMN IF NOT EXISTS leave_from date,
  ADD COLUMN IF NOT EXISTS leave_to date,
  ADD COLUMN IF NOT EXISTS leave_reason text,
  ADD COLUMN IF NOT EXISTS leave_leads_moved_at timestamptz,
  ADD COLUMN IF NOT EXISTS break_alert_sent_at timestamptz;

ALTER TABLE public.callers DROP CONSTRAINT IF EXISTS callers_calling_mode_check;
ALTER TABLE public.callers ADD CONSTRAINT callers_calling_mode_check
  CHECK (calling_mode IN ('business_default', 'sim', 'cloud'));

ALTER TABLE public.callers DROP CONSTRAINT IF EXISTS callers_leave_dates_check;
ALTER TABLE public.callers ADD CONSTRAINT callers_leave_dates_check
  CHECK (leave_from IS NULL OR leave_to IS NULL OR leave_to >= leave_from);
