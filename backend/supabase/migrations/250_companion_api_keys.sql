-- 250_companion_api_keys.sql
-- Aira Companion chat API: the business's secret keys (companion-chat-api).
--
-- - companion_api_keys: one row per secret key. Only the SHA-256 of the key is stored; the full
--   key ("acs_live_...") is shown once, when it is created in the dashboard.
--   Example: Astrotamil creates a key, pastes it into their server, and their server
--     1. calls POST /api/v1/companion/chat with "Authorization: Bearer acs_live_..."
--     2. signs each user id for the web widget (HMAC-SHA256, keyed by the SHA-256 of the key,
--        so Anril can check the signature without ever storing the key itself).
-- - At most 2 active keys per business (checked in code), so a key can be rotated with no
--   downtime: create the new one, swap it in, revoke the old one.
-- - last_used_at is a heartbeat for the Install tab ("last used 3 min ago").
--
-- RLS on with no policies: service role only, like 248. No operator route reads this table.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_api_keys (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key_prefix   text NOT NULL CHECK (length(key_prefix) BETWEEN 8 AND 24),
  key_hash     text NOT NULL UNIQUE CHECK (length(key_hash) = 64),
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  created_by   uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  revoked_at   timestamptz,
  last_used_at timestamptz
);

CREATE INDEX IF NOT EXISTS companion_api_keys_tenant_active
  ON companion_api_keys (tenant_id) WHERE status = 'active';

ALTER TABLE companion_api_keys ENABLE ROW LEVEL SECURITY;
