-- 295: Orders & payments — quotes with an Accept button, and refunds.
--
-- * Quotes are deals in stage 'quoted' with a validity date, an advance asked on Accept
--   and a "ready in N days". Accepting (WhatsApp button or the quote page) moves the deal to
--   awaiting_payment and sends the advance link. Unanswered: one reminder after 2 days;
--   past the valid date: lost, "Quote expired".
-- * deal_refunds: money given back (Razorpay, cash, UPI, bank). deals.refunded_paise is their
--   sum, kept by a trigger. A refund on a GST invoice gets a credit note number per
--   financial year ("CN/2026-27/0001"), from invoice_counters under fy 'CN/<fy>'.

ALTER TABLE deals
  ADD COLUMN IF NOT EXISTS quote_valid_until date,
  ADD COLUMN IF NOT EXISTS quote_sent_at timestamptz,
  ADD COLUMN IF NOT EXISTS quote_reminded_at timestamptz,
  ADD COLUMN IF NOT EXISTS accepted_at timestamptz,
  ADD COLUMN IF NOT EXISTS advance_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ready_in_days integer,
  ADD COLUMN IF NOT EXISTS refunded_paise bigint NOT NULL DEFAULT 0;

ALTER TABLE deals
  ADD CONSTRAINT deals_advance_paise_check CHECK (advance_paise >= 0),
  ADD CONSTRAINT deals_refunded_paise_check CHECK (refunded_paise >= 0),
  ADD CONSTRAINT deals_ready_in_days_check CHECK (ready_in_days IS NULL OR ready_in_days BETWEEN 0 AND 365);

CREATE INDEX IF NOT EXISTS deals_open_quotes_idx ON deals (quote_sent_at) WHERE stage = 'quoted' AND quote_sent_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS deal_refunds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  deal_id uuid NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
  amount_paise bigint NOT NULL CHECK (amount_paise > 0),
  method text NOT NULL CHECK (method IN ('razorpay', 'cash', 'upi', 'bank_transfer', 'other')),
  reason text,
  status text NOT NULL DEFAULT 'done' CHECK (status IN ('done', 'pending', 'failed')),
  razorpay_payment_id text,
  razorpay_refund_id text,
  credit_note_number text,
  restocked boolean NOT NULL DEFAULT false,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS deal_refunds_deal_idx ON deal_refunds (deal_id);
CREATE INDEX IF NOT EXISTS deal_refunds_tenant_created_idx ON deal_refunds (tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS deal_refunds_razorpay_key ON deal_refunds (razorpay_refund_id) WHERE razorpay_refund_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS deal_refunds_credit_note_key ON deal_refunds (tenant_id, credit_note_number) WHERE credit_note_number IS NOT NULL;
ALTER TABLE deal_refunds ENABLE ROW LEVEL SECURITY;
CREATE POLICY deal_refunds_tenant_member_select ON deal_refunds
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- A failed Razorpay refund gave nothing back, so it doesn't count.
CREATE OR REPLACE FUNCTION deal_refunds_sync_refunded()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_deal uuid := COALESCE(NEW.deal_id, OLD.deal_id);
BEGIN
  UPDATE deals d
     SET refunded_paise = COALESCE((SELECT sum(r.amount_paise) FROM deal_refunds r
                                     WHERE r.deal_id = v_deal AND r.status <> 'failed'), 0)
   WHERE d.id = v_deal;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS deal_refunds_sync_refunded_trg ON deal_refunds;
CREATE TRIGGER deal_refunds_sync_refunded_trg
  AFTER INSERT OR UPDATE OR DELETE ON deal_refunds
  FOR EACH ROW EXECUTE FUNCTION deal_refunds_sync_refunded();

ALTER TABLE deal_messages DROP CONSTRAINT IF EXISTS deal_messages_kind_check;
ALTER TABLE deal_messages ADD CONSTRAINT deal_messages_kind_check
  CHECK (kind IN ('bill', 'confirmed', 'ready', 'shipped', 'delivered', 'reminder', 'pay_link', 'quote', 'quote_reminder', 'refund'));
