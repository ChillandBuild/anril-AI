-- 294: Commerce > Orders & payments (deals become orders).
--
-- * deal_payments: every payment on an order (advance, balance, full). deals.paid_paise
--   is their sum, kept by a trigger. An order is "won" (Paid) only when paid in full;
--   before that it stays awaiting_payment and shows as "Advance paid".
-- * deals: shop or online, how it reaches the customer (taken now / pickup / courier),
--   delivery steps, discount, GST bill or simple bill, buyer GSTIN for B2B, the invoice
--   number (per financial year) and a secret token for the customer's bill page.
--   lead_id becomes optional: a walk-in with no number still makes an order.
-- * deal_messages: what was sent to the customer about the order (bill, ready, shipped,
--   reminder). Ticks come from messages.delivery_status through message_id.
-- * catalog_item_variants: sizes x colours, each with its own stock. The item's own
--   stock_quantity stays the sum, so the AI and older code keep reading one number.
-- * stock_waitlist: "tell me when back" for a sold-out size.
-- Existing won deals get one payment row each, so their money stays counted.

-- ── Orders ──────────────────────────────────────────────────────────────────────
ALTER TABLE deals ALTER COLUMN lead_id DROP NOT NULL;

ALTER TABLE deals
  ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'online',
  ADD COLUMN IF NOT EXISTS handover text,
  ADD COLUMN IF NOT EXISTS delivery_status text NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS ready_by date,
  ADD COLUMN IF NOT EXISTS ready_at timestamptz,
  ADD COLUMN IF NOT EXISTS shipped_at timestamptz,
  ADD COLUMN IF NOT EXISTS delivered_at timestamptz,
  ADD COLUMN IF NOT EXISTS courier text,
  ADD COLUMN IF NOT EXISTS tracking_id text,
  ADD COLUMN IF NOT EXISTS discount_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS gst_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS bill_type text NOT NULL DEFAULT 'gst',
  ADD COLUMN IF NOT EXISTS buyer_gstin text,
  ADD COLUMN IF NOT EXISTS buyer_business text,
  ADD COLUMN IF NOT EXISTS customer_name text,
  ADD COLUMN IF NOT EXISTS sold_by_ai boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS invoice_number text,
  ADD COLUMN IF NOT EXISTS invoice_issued_at timestamptz,
  ADD COLUMN IF NOT EXISTS bill_token text,
  ADD COLUMN IF NOT EXISTS paid_paise bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reminders_sent integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reminders_from timestamptz,
  ADD COLUMN IF NOT EXISTS last_reminder_at timestamptz;

ALTER TABLE deals
  ADD CONSTRAINT deals_channel_check CHECK (channel IN ('online', 'store')),
  ADD CONSTRAINT deals_handover_check CHECK (handover IS NULL OR handover IN ('taken', 'pickup', 'courier')),
  ADD CONSTRAINT deals_delivery_status_check CHECK (delivery_status IN ('none', 'working', 'ready', 'shipped', 'delivered')),
  ADD CONSTRAINT deals_discount_check CHECK (discount_paise >= 0),
  ADD CONSTRAINT deals_gst_paise_check CHECK (gst_paise >= 0),
  ADD CONSTRAINT deals_bill_type_check CHECK (bill_type IN ('gst', 'simple')),
  ADD CONSTRAINT deals_paid_paise_check CHECK (paid_paise >= 0),
  ADD CONSTRAINT deals_buyer_gstin_check CHECK (buyer_gstin IS NULL OR buyer_gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),
  ADD CONSTRAINT deals_customer_needed CHECK (lead_id IS NOT NULL OR channel = 'store');

CREATE UNIQUE INDEX IF NOT EXISTS deals_tenant_invoice_number_key ON deals (tenant_id, invoice_number) WHERE invoice_number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS deals_bill_token_key ON deals (bill_token) WHERE bill_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS deals_tenant_created_idx ON deals (tenant_id, created_at DESC);

-- ── Payments ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deal_payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  deal_id uuid NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
  amount_paise bigint NOT NULL CHECK (amount_paise > 0),
  method text NOT NULL CHECK (method IN ('razorpay', 'cash', 'upi', 'card', 'bank_transfer', 'other')),
  kind text NOT NULL DEFAULT 'payment' CHECK (kind IN ('advance', 'balance', 'full', 'payment')),
  razorpay_payment_id text,
  received_by uuid,
  received_by_caller uuid REFERENCES callers(id) ON DELETE SET NULL,
  note text,
  paid_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS deal_payments_deal_idx ON deal_payments (deal_id);
CREATE INDEX IF NOT EXISTS deal_payments_tenant_paid_idx ON deal_payments (tenant_id, paid_at DESC);
-- One row per Razorpay payment: a retried webhook can never count the money twice.
CREATE UNIQUE INDEX IF NOT EXISTS deal_payments_razorpay_key ON deal_payments (razorpay_payment_id) WHERE razorpay_payment_id IS NOT NULL;

ALTER TABLE deal_payments ENABLE ROW LEVEL SECURITY;
CREATE POLICY deal_payments_tenant_member_select ON deal_payments
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE OR REPLACE FUNCTION deal_payments_sync_paid()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_deal uuid := COALESCE(NEW.deal_id, OLD.deal_id);
BEGIN
  UPDATE deals d
     SET paid_paise = COALESCE((SELECT sum(p.amount_paise) FROM deal_payments p WHERE p.deal_id = v_deal), 0)
   WHERE d.id = v_deal;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS deal_payments_sync_paid_trg ON deal_payments;
CREATE TRIGGER deal_payments_sync_paid_trg
  AFTER INSERT OR UPDATE OR DELETE ON deal_payments
  FOR EACH ROW EXECUTE FUNCTION deal_payments_sync_paid();

-- Today's paid deals: one full payment each, dated when they were won.
INSERT INTO deal_payments (tenant_id, deal_id, amount_paise, method, kind, razorpay_payment_id, paid_at)
SELECT d.tenant_id, d.id, d.total_paise, COALESCE(d.payment_method, 'other'), 'full',
       d.razorpay_payment_id, COALESCE(d.won_at, d.updated_at, d.created_at)
  FROM deals d
 WHERE d.stage = 'won' AND d.total_paise > 0
   AND NOT EXISTS (SELECT 1 FROM deal_payments p WHERE p.deal_id = d.id);

-- ── Messages sent about an order ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deal_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  deal_id uuid NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('bill', 'confirmed', 'ready', 'shipped', 'delivered', 'reminder', 'pay_link')),
  sent_via text NOT NULL CHECK (sent_via IN ('text', 'template', 'share')),
  message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  body text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS deal_messages_deal_idx ON deal_messages (deal_id, created_at);
ALTER TABLE deal_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY deal_messages_tenant_member_select ON deal_messages
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- ── Invoice numbers, per business and financial year ("2026-27/0042") ────────────
CREATE TABLE IF NOT EXISTS invoice_counters (
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  fy text NOT NULL,
  last_number integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, fy)
);
ALTER TABLE invoice_counters ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION next_invoice_number(p_tenant_id uuid, p_fy text)
RETURNS integer
LANGUAGE sql
SET search_path TO 'public', 'pg_temp'
AS $$
  INSERT INTO invoice_counters (tenant_id, fy, last_number) VALUES (p_tenant_id, p_fy, 1)
  ON CONFLICT (tenant_id, fy) DO UPDATE SET last_number = invoice_counters.last_number + 1
  RETURNING last_number;
$$;

-- ── Sizes x colours ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS catalog_item_variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  size text,
  colour text,
  stock_quantity integer NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
  price_paise bigint CHECK (price_paise IS NULL OR price_paise >= 0),
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (size IS NOT NULL OR colour IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS catalog_item_variants_unique
  ON catalog_item_variants (catalog_item_id, lower(COALESCE(size, '')), lower(COALESCE(colour, '')));
ALTER TABLE catalog_item_variants ENABLE ROW LEVEL SECURITY;
CREATE POLICY catalog_item_variants_tenant_member_select ON catalog_item_variants
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE deal_items
  ADD COLUMN IF NOT EXISTS variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS variant_label text;

ALTER TABLE stock_movements
  ADD COLUMN IF NOT EXISTS variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS variant_quantity_after integer;

-- One size/colour's stock moves, and the item's total moves with it, in one statement each.
CREATE OR REPLACE FUNCTION apply_variant_stock_movement(
  p_tenant_id uuid, p_variant_id uuid, p_delta integer, p_reason text,
  p_deal_id uuid DEFAULT NULL, p_note text DEFAULT NULL, p_created_by uuid DEFAULT NULL)
RETURNS TABLE(ok boolean, quantity_after integer, item_quantity_after integer)
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_item uuid;
  v_after integer;
  v_item_after integer;
BEGIN
  UPDATE catalog_item_variants
     SET stock_quantity = stock_quantity + p_delta
   WHERE id = p_variant_id AND tenant_id = p_tenant_id AND stock_quantity + p_delta >= 0
  RETURNING catalog_item_id, stock_quantity INTO v_item, v_after;
  IF v_after IS NULL THEN
    RETURN QUERY SELECT false, (SELECT v.stock_quantity FROM catalog_item_variants v
                                 WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id), NULL::integer;
    RETURN;
  END IF;
  UPDATE catalog_items
     SET stock_quantity = (SELECT COALESCE(sum(v.stock_quantity), 0)::integer
                             FROM catalog_item_variants v WHERE v.catalog_item_id = v_item)
   WHERE id = v_item AND tenant_id = p_tenant_id
  RETURNING stock_quantity INTO v_item_after;
  INSERT INTO stock_movements (tenant_id, catalog_item_id, variant_id, delta, quantity_after,
                               variant_quantity_after, reason, deal_id, note, created_by)
  VALUES (p_tenant_id, v_item, p_variant_id, p_delta, v_item_after, v_after, p_reason, p_deal_id, p_note, p_created_by);
  RETURN QUERY SELECT true, v_after, v_item_after;
END $$;

-- ── "Tell me when back" for a sold-out size ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock_waitlist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  phone text,
  name text,
  created_by uuid,
  notified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (lead_id IS NOT NULL OR phone IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS stock_waitlist_item_idx ON stock_waitlist (tenant_id, catalog_item_id) WHERE notified_at IS NULL;
ALTER TABLE stock_waitlist ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_waitlist_tenant_member_select ON stock_waitlist
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
