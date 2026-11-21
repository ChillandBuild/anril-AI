-- 307: Purchases & suppliers (Commerce mockup: Purchase orders, Stock in, Suppliers).
-- * suppliers: who the business buys from.
-- * purchase_orders / purchase_order_lines: what was asked for (PO-0001...), sent on WhatsApp,
--   confirmed by the supplier's button, received in one or more stock-ins.
-- * stock_ins / stock_in_lines: what came (with or without a PO). Good pieces go into stock
--   through apply_stock_movement / apply_variant_stock_movement (reason 'restock') at a place;
--   damaged pieces are kept aside with what to do about them.
-- * supplier_payments: money paid to a supplier. Dues = bills - payments (computed in code).
-- Members read their own rows; only the backend writes.

CREATE TABLE IF NOT EXISTS suppliers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
  phone text,
  city text,
  gstin text,
  supplies text,                         -- "Silk, Kanchi pattu"
  archived boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS suppliers_name_uq ON suppliers (tenant_id, lower(btrim(name))) WHERE NOT archived;

CREATE TABLE IF NOT EXISTS purchase_counters (
  tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  last_number integer NOT NULL DEFAULT 0
);
CREATE OR REPLACE FUNCTION next_po_number(p_tenant_id uuid)
RETURNS integer
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  INSERT INTO purchase_counters (tenant_id, last_number) VALUES (p_tenant_id, 1)
  ON CONFLICT (tenant_id) DO UPDATE SET last_number = purchase_counters.last_number + 1
  RETURNING last_number;
$$;

CREATE TABLE IF NOT EXISTS purchase_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  number integer NOT NULL,
  supplier_id uuid NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'sent', 'confirmed', 'part_received', 'received', 'cancelled')),
  need_by date,
  place_id uuid REFERENCES stock_places(id) ON DELETE SET NULL,
  note text,
  items_paise bigint NOT NULL DEFAULT 0,
  gst_paise bigint NOT NULL DEFAULT 0,
  sent_at timestamptz,
  sent_via text CHECK (sent_via IS NULL OR sent_via IN ('text', 'template', 'share')),
  confirmed_at timestamptz,
  date_change_asked_at timestamptz,
  reminded_at timestamptz,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, number)
);
CREATE INDEX IF NOT EXISTS purchase_orders_tenant_idx ON purchase_orders (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE SET NULL,
  label text NOT NULL,
  qty_ordered integer NOT NULL CHECK (qty_ordered > 0),
  qty_received integer NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
  unit_cost_paise bigint NOT NULL CHECK (unit_cost_paise >= 0),
  gst_rate numeric(5, 2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS purchase_order_lines_po_idx ON purchase_order_lines (purchase_order_id);

CREATE TABLE IF NOT EXISTS stock_ins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  supplier_id uuid REFERENCES suppliers(id) ON DELETE SET NULL,
  purchase_order_id uuid REFERENCES purchase_orders(id) ON DELETE SET NULL,
  bill_no text,
  bill_date date NOT NULL DEFAULT CURRENT_DATE,
  supplier_gstin text,
  place_id uuid REFERENCES stock_places(id) ON DELETE SET NULL,
  received_by text,
  items_paise bigint NOT NULL DEFAULT 0,      -- good pieces only (what is owed)
  gst_paise bigint NOT NULL DEFAULT 0,
  total_paise bigint NOT NULL DEFAULT 0,
  pay_status text NOT NULL DEFAULT 'later' CHECK (pay_status IN ('paid', 'part', 'later')),
  due_date date,
  photo_path text,
  applied_at timestamptz,                     -- stock moved in
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stock_ins_tenant_idx ON stock_ins (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS stock_ins_supplier_idx ON stock_ins (supplier_id);

CREATE TABLE IF NOT EXISTS stock_in_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  stock_in_id uuid NOT NULL REFERENCES stock_ins(id) ON DELETE CASCADE,
  purchase_order_line_id uuid REFERENCES purchase_order_lines(id) ON DELETE SET NULL,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE SET NULL,
  label text NOT NULL,
  qty_good integer NOT NULL DEFAULT 0 CHECK (qty_good >= 0),
  qty_damaged integer NOT NULL DEFAULT 0 CHECK (qty_damaged >= 0),
  damaged_action text CHECK (damaged_action IS NULL OR damaged_action IN ('replace', 'less_on_bill', 'discount')),
  unit_cost_paise bigint NOT NULL CHECK (unit_cost_paise >= 0),
  gst_rate numeric(5, 2) NOT NULL DEFAULT 0,
  CHECK (qty_good + qty_damaged > 0)
);
CREATE INDEX IF NOT EXISTS stock_in_lines_in_idx ON stock_in_lines (stock_in_id);

CREATE TABLE IF NOT EXISTS supplier_payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  supplier_id uuid NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  stock_in_id uuid REFERENCES stock_ins(id) ON DELETE SET NULL,
  amount_paise bigint NOT NULL CHECK (amount_paise > 0),
  method text NOT NULL DEFAULT 'upi' CHECK (method IN ('cash', 'upi', 'bank', 'cheque')),
  paid_on date NOT NULL DEFAULT CURRENT_DATE,
  note text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS supplier_payments_supplier_idx ON supplier_payments (tenant_id, supplier_id);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['suppliers', 'purchase_orders', 'purchase_order_lines', 'stock_ins', 'stock_in_lines',
                           'supplier_payments', 'purchase_counters'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    IF t <> 'purchase_counters' THEN
      EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (is_tenant_member(tenant_id))',
                     t || '_tenant_member_select', t);
    END IF;
  END LOOP;
END $$;
REVOKE EXECUTE ON FUNCTION next_po_number(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION next_po_number(uuid) TO service_role;

-- Cost price is what the latest stock-in paid (Purchases), so profit is real.
ALTER TABLE catalog_item_variants ADD COLUMN IF NOT EXISTS cost_price_paise bigint
  CHECK (cost_price_paise IS NULL OR cost_price_paise >= 0);
