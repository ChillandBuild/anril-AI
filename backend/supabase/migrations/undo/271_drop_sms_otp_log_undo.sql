-- Undo 271_drop_sms_otp_log.sql: recreate the empty table as 239 + 240 left it.
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS sms_otp_log (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  mobile          text NOT NULL,
  action          text NOT NULL CHECK (action IN ('send', 'resend', 'verify')),
  ok              boolean NOT NULL,
  request_id      text,
  message         text,
  created_by      uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  delivery_status text,
  delivered_at    timestamptz,
  amount_debited  numeric(12,4)
);
CREATE INDEX IF NOT EXISTS sms_otp_log_tenant_idx ON sms_otp_log (tenant_id, created_at DESC);
ALTER TABLE sms_otp_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sms_otp_log FROM anon, authenticated;
GRANT ALL ON sms_otp_log TO service_role;
