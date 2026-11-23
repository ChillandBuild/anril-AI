-- Undo 344_invoice_on_link_paid.sql
ALTER TABLE public.deals DROP COLUMN IF EXISTS send_invoice_on_paid;
