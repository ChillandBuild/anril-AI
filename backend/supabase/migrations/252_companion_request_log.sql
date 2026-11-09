-- 252_companion_request_log.sql
-- Anril Agents "Requests" page: one row per call to the public companion API
-- (server /chat, /chat/continue; widget /session, /chat, /chat/continue).
-- Example: Karthik chats on astrotamil.com → a row
--   (Astrotamil, Jothidar AI, 'widget_chat', '48213', 200, 1400 ms, 10:42).
--
-- - No message text column, on purpose: the log says who called what, when, and how it went,
--   never what was said.
-- - Rows are written after the response is sent; a failed insert never fails a chat.
-- - Calls rejected before the business is known (bad key, bad signature, IP rate limit) are not
--   logged: there is no tenant to log them under.
-- - companion_id is the id the caller sent (null for /continue calls, which send a turn id). No
--   foreign key: a wrong or deleted id must still be logged (as a 404), and the dashboard only
--   names this business's own characters.
--
-- RLS on with no policies: service role only, like 248 and 250.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_request_log (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id     uuid,
  kind             text NOT NULL CHECK (kind IN
                     ('chat', 'chat_continue', 'widget_session', 'widget_chat', 'widget_continue')),
  external_user_id text CHECK (length(external_user_id) <= 200),
  status           smallint NOT NULL CHECK (status BETWEEN 100 AND 599),
  ms               integer NOT NULL CHECK (ms >= 0),
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS companion_request_log_tenant_created
  ON companion_request_log (tenant_id, created_at DESC);

ALTER TABLE companion_request_log ENABLE ROW LEVEL SECURITY;
