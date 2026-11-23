-- 344_invoice_on_link_paid.sql  (v9.2 Chats > Record payment: GST invoice with the WhatsApp link)
-- Additive only. A Record payment sent as a WhatsApp payment link can ask for the GST invoice to go
-- out by itself once the customer pays: the Razorpay paid webhook reads this flag and sends the bill
-- (Orders > Send bill) instead of the plain "Payment received" line.
-- Undo: undo/344_invoice_on_link_paid_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS send_invoice_on_paid boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN public.deals.send_invoice_on_paid IS
  'Record payment by link with "Send GST invoice": when the link is paid in full, send the bill on WhatsApp.';
