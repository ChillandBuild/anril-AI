-- Undo 305.
DROP INDEX IF EXISTS stock_waitlist_asked_idx;
DROP INDEX IF EXISTS stock_waitlist_open_uq;
ALTER TABLE stock_waitlist
  DROP COLUMN IF EXISTS notify_via,
  DROP COLUMN IF EXISTS closed_at,
  DROP COLUMN IF EXISTS price_paise,
  DROP COLUMN IF EXISTS last_asked_at,
  DROP COLUMN IF EXISTS wants_message,
  DROP COLUMN IF EXISTS source;
