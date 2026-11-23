-- 347_booking_pickup.sql  (v9.2 Bookings > Site visits: where to pick the buyer up)
-- Additive only. A short note per booking, e.g. "From Chatram bus stand" or "Own vehicle".
-- Undo: undo/347_booking_pickup_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS pickup text
  CHECK (pickup IS NULL OR length(pickup) <= 120);
