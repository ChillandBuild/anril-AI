-- 337_bill_client_ref.sql  (v9.2 #74 offline billing)
-- deals.client_ref: a "send once" key the New bill page makes on the device. A bill saved while offline is sent
-- again when the internet is back; if the first try had in fact reached us, the same key returns that bill
-- instead of making a second one. Unique per business; NULL for every bill made before this or without a key.
-- Additive only. RLS on deals is unchanged.
-- Undo: undo/337_bill_client_ref_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS client_ref text
  CHECK (client_ref IS NULL OR length(client_ref) BETWEEN 8 AND 64);
CREATE UNIQUE INDEX IF NOT EXISTS deals_tenant_client_ref_key
  ON public.deals (tenant_id, client_ref) WHERE client_ref IS NOT NULL;
