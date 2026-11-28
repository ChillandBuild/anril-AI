-- 351_companion_app_data_log.sql
-- What the business's app sent about the person with each live reply, kept 7 days (AstroTamil, 27 Nov 2026:
-- "save the chart data sent with each AI reply, birth details removed, so we can see what the AI received").
--
-- Example: Manjari asks Jothidar AI "Velai eppo?" at 10:02 → one row:
--   (Astrotamil, Jothidar AI, Manjari's person row, <the reply's message id>,
--    '{"lagnam":"சிம்மம்","dasa":"குரு தசை","bhukti":"ராகு புத்தி", ...}', 10:02)
--   with the birth date, time and place already removed by the backend (birth_guard.strip_app_data).
-- The nightly job companion-app-data-prune (03:20 IST) deletes rows older than 7 days.
--
-- The row hangs off the reply: deleting the message, the person ("forget me") or the character deletes it too.
-- Add-only: one new table, one index. No existing table or row is touched.
-- RLS on with no policies: service role only, like 349.
-- Apply BEFORE the backend that writes it is deployed (without the table the write only logs a warning).

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_app_data_log (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id  uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id   uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  message_id    uuid NOT NULL UNIQUE REFERENCES companion_messages(id) ON DELETE CASCADE,
  app_data      text NOT NULL CHECK (length(app_data) BETWEEN 1 AND 12000),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS companion_app_data_log_created
  ON companion_app_data_log (created_at);

ALTER TABLE companion_app_data_log ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE companion_app_data_log IS
  'The app data (birth details removed) sent with each live Anril Agents reply. Kept 7 days (companion-app-data-prune).';
