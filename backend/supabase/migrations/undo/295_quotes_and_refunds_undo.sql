-- Undo 295.
ALTER TABLE deal_messages DROP CONSTRAINT IF EXISTS deal_messages_kind_check;
DELETE FROM deal_messages WHERE kind IN ('quote', 'quote_reminder', 'refund');
ALTER TABLE deal_messages ADD CONSTRAINT deal_messages_kind_check
  CHECK (kind IN ('bill', 'confirmed', 'ready', 'shipped', 'delivered', 'reminder', 'pay_link'));
DROP TRIGGER IF EXISTS deal_refunds_sync_refunded_trg ON deal_refunds;
DROP FUNCTION IF EXISTS deal_refunds_sync_refunded();
DROP TABLE IF EXISTS deal_refunds;
DROP INDEX IF EXISTS deals_open_quotes_idx;
ALTER TABLE deals
  DROP CONSTRAINT IF EXISTS deals_ready_in_days_check,
  DROP CONSTRAINT IF EXISTS deals_refunded_paise_check,
  DROP CONSTRAINT IF EXISTS deals_advance_paise_check;
ALTER TABLE deals
  DROP COLUMN IF EXISTS refunded_paise, DROP COLUMN IF EXISTS ready_in_days, DROP COLUMN IF EXISTS advance_paise,
  DROP COLUMN IF EXISTS accepted_at, DROP COLUMN IF EXISTS quote_reminded_at, DROP COLUMN IF EXISTS quote_sent_at,
  DROP COLUMN IF EXISTS quote_valid_until;
