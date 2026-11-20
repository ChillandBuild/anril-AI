-- 296: Orders & payments — Day closing, cash spent, and the advance-rule note on an order.
--
-- * cash_expenses: cash taken out of the drawer for the day (tea, transport...). Until the
--   Expenses tab exists, Day closing is where they are typed.
-- * day_closings: one row per business per day: opening cash, cash sales, cash refunds, cash
--   spent, what the drawer should hold, what was counted and the difference. Closing again
--   the same day replaces the row (the activity log keeps every close).
-- * deals.advance_note: "Advance rule 30% (₹3,150) · staff changed it to ₹3,000 for this order".
-- * deal_refunds.items: the lines a part refund put back on the shelf ([{deal_item_id, qty}]),
--   so the same piece can't be returned twice.

CREATE TABLE IF NOT EXISTS cash_expenses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  day date NOT NULL,
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  amount_paise bigint NOT NULL CHECK (amount_paise > 0),
  spent_by text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cash_expenses_tenant_day_idx ON cash_expenses (tenant_id, day);
ALTER TABLE cash_expenses ENABLE ROW LEVEL SECURITY;
CREATE POLICY cash_expenses_tenant_member_select ON cash_expenses
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS day_closings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  day date NOT NULL,
  opening_paise bigint NOT NULL DEFAULT 0 CHECK (opening_paise >= 0),
  cash_sales_paise bigint NOT NULL DEFAULT 0,
  cash_refunds_paise bigint NOT NULL DEFAULT 0,
  cash_expenses_paise bigint NOT NULL DEFAULT 0,
  expected_paise bigint NOT NULL DEFAULT 0,
  counted_paise bigint NOT NULL CHECK (counted_paise >= 0),
  difference_paise bigint NOT NULL DEFAULT 0,
  note text,
  closed_by uuid,
  closed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, day)
);
ALTER TABLE day_closings ENABLE ROW LEVEL SECURITY;
CREATE POLICY day_closings_tenant_member_select ON day_closings
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE deals ADD COLUMN IF NOT EXISTS advance_note text;

ALTER TABLE deal_refunds ADD COLUMN IF NOT EXISTS items jsonb;
