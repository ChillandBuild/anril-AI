-- Undo 296.
ALTER TABLE deal_refunds DROP COLUMN IF EXISTS items;
ALTER TABLE deals DROP COLUMN IF EXISTS advance_note;
DROP TABLE IF EXISTS day_closings;
DROP TABLE IF EXISTS cash_expenses;
