-- 336: property site visits (v9.2 screen 215). How a visit went, and the one-time home-loan follow-up.
-- Nullable columns on bookings only; no data is changed. Code works without this (the outcome button then
-- says "not ready yet" and the follow-up sweep does nothing).
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS visit_outcome          text;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS visit_outcome_at       timestamptz;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS loan_followup_due_at   timestamptz;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS loan_followup_sent_at  timestamptz;
CREATE INDEX IF NOT EXISTS idx_bookings_loan_followup
  ON public.bookings (loan_followup_due_at)
  WHERE loan_followup_due_at IS NOT NULL AND loan_followup_sent_at IS NULL;
