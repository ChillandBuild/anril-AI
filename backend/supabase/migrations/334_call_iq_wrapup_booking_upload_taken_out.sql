-- 334: Call IQ items 136 (Visit booked makes a booking) and 234 (uploads: what was taken out).
-- Additive and idempotent. No data is changed.
--
-- 136: the booking a wrap-up made, so saving the same wrap-up twice never makes a second booking.
-- 234: why rows of an upload were left out (bad number, repeated, said stop, already a customer, ...).
--      `taken_out` holds the rows (capped at 5000 by the code), `taken_out_counts` the full count per reason.
--      Older uploads keep NULL here and show a dash on the page.
-- 233 needs nothing new: the "why" of a scheduled call is follow_up_jobs.message_preview.
-- RLS: these tables already have it on; adding a column does not change that.

alter table public.call_logs
  add column if not exists booking_id uuid;

alter table public.telecalling_upload_batches
  add column if not exists taken_out jsonb,
  add column if not exists taken_out_counts jsonb;
