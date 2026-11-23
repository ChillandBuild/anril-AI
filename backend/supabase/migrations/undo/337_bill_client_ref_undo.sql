-- Undo 337_bill_client_ref.sql. Bills keep working; retried offline bills could then be made twice.
DROP INDEX IF EXISTS public.deals_tenant_client_ref_key;
ALTER TABLE public.deals DROP COLUMN IF EXISTS client_ref;
