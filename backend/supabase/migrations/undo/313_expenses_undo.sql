-- Undo 313. Expenses typed with UPI / bank / card stay, but Day closing would count them as cash again:
-- delete or review them first.
DROP INDEX IF EXISTS cash_expenses_repeat_month_uq;
ALTER TABLE cash_expenses DROP CONSTRAINT IF EXISTS cash_expenses_repeat_fk;
DROP TABLE IF EXISTS expense_repeats;
ALTER TABLE cash_expenses DROP COLUMN IF EXISTS repeat_month;
ALTER TABLE cash_expenses DROP COLUMN IF EXISTS repeat_id;
ALTER TABLE cash_expenses DROP COLUMN IF EXISTS bill_path;
ALTER TABLE cash_expenses DROP COLUMN IF EXISTS method;
ALTER TABLE cash_expenses DROP COLUMN IF EXISTS category;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS short_reminded_at;
