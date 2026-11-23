-- Undo 347_booking_pickup.sql
ALTER TABLE public.bookings DROP COLUMN IF EXISTS pickup;
