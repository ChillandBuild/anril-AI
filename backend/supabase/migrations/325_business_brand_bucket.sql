-- Business details & bills (v9.2): the shop's logo and signature for the bill.
-- Private bucket, written by the server only, read through a short signed link. 1 MB, png/jpg/webp.
-- Everything else (PAN, UPI, bank, bill prefix, terms...) lives in the existing business_details
-- settings row, so there is no new table.
INSERT INTO storage.buckets (id, name, public) VALUES ('business-brand', 'business-brand', false) ON CONFLICT (id) DO NOTHING;
UPDATE storage.buckets SET file_size_limit = 1048576, allowed_mime_types = ARRAY['image/png', 'image/jpeg', 'image/webp']
 WHERE id = 'business-brand';
