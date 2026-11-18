-- 281_leads_opted_out_source.sql
-- Customers > Said stop: record HOW a person got on the list, so the page can say it.
--
-- - opted_out_source: 'stop_reply' (replied STOP / unsubscribe), 'chat_ai' (the AI read a
--   clear no in chat), 'call' (telecaller ticked "stop messages"), 'staff' (added by hand).
--   NULL for people who stopped before this column existed ("Before we tracked how").
-- - opted_out_detail: short words for the Where column: the broadcast name, the caller's
--   name, what they wrote, or the staff member's name.
-- - opted_out_by: the user who added them by hand (staff only).
-- All three are cleared when the person is removed from Said stop.

SET LOCAL lock_timeout = '5s';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_source text
  CHECK (opted_out_source IS NULL OR opted_out_source IN ('stop_reply', 'chat_ai', 'call', 'staff'));
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_detail text
  CHECK (opted_out_detail IS NULL OR length(opted_out_detail) <= 200);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opted_out_by uuid;
