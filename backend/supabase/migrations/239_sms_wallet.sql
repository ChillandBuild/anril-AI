-- 239_sms_wallet.sql
-- SMS balance history and per-message charges for the client SMS page.
--
-- Bulk9 has no wallet-history API, so Anril builds one:
-- - sms_messages.amount_debited: what Bulk9 debited from the CLIENT's own wallet for that SMS
--   (the webhook's amount_debited, at the rate Anril set for the client). Never Anril's cost.
-- - sms_wallet: last balance Anril saw per tenant (the sms-balance-sync job, every 15 minutes),
--   plus when the low-balance alert last fired (cleared once the balance is back above it).
-- - sms_wallet_events: balance changes Anril's own sends don't explain. A rise is a top-up
--   (the operator added credit in the Bulk9 reseller panel); a fall is usage outside Anril
--   (the client's API key used directly). Campaign spends are read from sms_messages.
--
-- - sms_campaigns.deleted_at: "Delete" on a finished or cancelled campaign hides it from the
--   Campaigns list. The rows stay, so balance history keeps its spend and the balance sync never
--   sees an SMS vanish (which would read as usage outside Anril).
-- - sms_otp_log: OTPs sent, resent and checked from the Anril dashboard (Reports → OTP history).
--   The code itself is never stored; Bulk9 has no OTP-history API.
--
-- Writes come from the backend's service role only, like 237. Additive: safe to apply before
-- the backend that reads it is deployed.

SET LOCAL lock_timeout = '5s';

ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS amount_debited numeric(12,4);

CREATE TABLE IF NOT EXISTS sms_wallet (
  tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  sms_count integer NOT NULL,
  checked_at timestamptz NOT NULL,
  low_alerted_at timestamptz
);

CREATE TABLE IF NOT EXISTS sms_wallet_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('topup', 'outside_usage')),
  sms_delta integer NOT NULL,
  balance_after integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sms_wallet_events_tenant_idx ON sms_wallet_events (tenant_id, created_at DESC);

ALTER TABLE sms_campaigns ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

CREATE TABLE IF NOT EXISTS sms_otp_log (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  mobile     text NOT NULL,
  action     text NOT NULL CHECK (action IN ('send', 'resend', 'verify')),
  ok         boolean NOT NULL,
  request_id text,
  message    text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sms_otp_log_tenant_idx ON sms_otp_log (tenant_id, created_at DESC);

ALTER TABLE sms_wallet ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_wallet_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_otp_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sms_wallet, sms_wallet_events, sms_otp_log FROM anon, authenticated;
GRANT ALL ON sms_wallet, sms_wallet_events, sms_otp_log TO service_role;
-- No member policies: clients read these through /api/v1/sms/wallet/history and /otp/history only.
