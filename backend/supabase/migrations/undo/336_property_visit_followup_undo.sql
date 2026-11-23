-- Undo 336. Drops the visit outcome and loan follow-up columns (their values are lost).
DROP INDEX IF EXISTS public.idx_bookings_loan_followup;
ALTER TABLE public.bookings DROP COLUMN IF EXISTS loan_followup_sent_at;
ALTER TABLE public.bookings DROP COLUMN IF EXISTS loan_followup_due_at;
ALTER TABLE public.bookings DROP COLUMN IF EXISTS visit_outcome_at;
ALTER TABLE public.bookings DROP COLUMN IF EXISTS visit_outcome;
