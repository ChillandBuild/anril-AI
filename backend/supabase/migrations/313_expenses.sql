-- 313: Expenses (plan: docs/plans/commerce-stock-plan.md, "The rest").
--
-- cash_expenses (296, Day closing) becomes every expense: a category, how it was paid (cash / UPI /
-- bank / card; Day closing's drawer counts only cash), an optional bill photo, and the repeat it came
-- from. expense_repeats: rent, salary… added by themselves on their day each month (once a month).

ALTER TABLE cash_expenses ADD COLUMN IF NOT EXISTS category text NOT NULL DEFAULT 'other'
  CHECK (category IN ('rent', 'salary', 'electricity', 'transport', 'food', 'packing', 'other'));
ALTER TABLE cash_expenses ADD COLUMN IF NOT EXISTS method text NOT NULL DEFAULT 'cash'
  CHECK (method IN ('cash', 'upi', 'bank', 'card'));
ALTER TABLE cash_expenses ADD COLUMN IF NOT EXISTS bill_path text CHECK (bill_path IS NULL OR length(bill_path) <= 300);
ALTER TABLE cash_expenses ADD COLUMN IF NOT EXISTS repeat_id uuid;
ALTER TABLE cash_expenses ADD COLUMN IF NOT EXISTS repeat_month date;  -- first day of the month it is for

CREATE TABLE IF NOT EXISTS expense_repeats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  category text NOT NULL CHECK (category IN ('rent', 'salary', 'electricity', 'transport', 'food', 'packing', 'other')),
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  amount_paise bigint NOT NULL CHECK (amount_paise > 0),
  method text NOT NULL DEFAULT 'bank' CHECK (method IN ('cash', 'upi', 'bank', 'card')),
  day_of_month integer NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
  active boolean NOT NULL DEFAULT true,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS expense_repeats_tenant_idx ON expense_repeats (tenant_id) WHERE active;
ALTER TABLE expense_repeats ENABLE ROW LEVEL SECURITY;
CREATE POLICY expense_repeats_tenant_member_select ON expense_repeats
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE cash_expenses ADD CONSTRAINT cash_expenses_repeat_fk
  FOREIGN KEY (repeat_id) REFERENCES expense_repeats(id) ON DELETE SET NULL;
-- A repeat is added once a month, even if the daily job runs twice.
CREATE UNIQUE INDEX IF NOT EXISTS cash_expenses_repeat_month_uq ON cash_expenses (repeat_id, repeat_month)
  WHERE repeat_id IS NOT NULL;

-- Bill photos of expenses: private (read through a short signed link), written by the server only.
INSERT INTO storage.buckets (id, name, public) VALUES ('expense-bills', 'expense-bills', false) ON CONFLICT (id) DO NOTHING;

-- Purchases: pieces still to come on a part-received order get one reminder to the supplier on the
-- expected date (inside WhatsApp's 24-hour window; otherwise the owner is told to send it).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS short_reminded_at timestamptz;
