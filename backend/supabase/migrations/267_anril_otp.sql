-- 267_anril_otp.sql
-- Anril OTP: one-time codes sent by SMS (Bulk9 DLT), WhatsApp (Meta authentication template),
-- both, or SMS-then-WhatsApp. Spec: docs/specs/anril-otp.md. Additive only.
-- The plain code is never stored: Anril-made codes keep an HMAC hash; client-made codes keep
-- only a masked copy for history.

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------- per-tenant settings
CREATE TABLE IF NOT EXISTS otp_settings (
  tenant_id             uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  default_mode          text NOT NULL DEFAULT 'sms_then_whatsapp'
                        CHECK (default_mode IN ('sms', 'whatsapp', 'both', 'sms_then_whatsapp')),
  fallback_wait_seconds integer NOT NULL DEFAULT 30 CHECK (fallback_wait_seconds BETWEEN 10 AND 300),
  max_per_hour          integer NOT NULL DEFAULT 5 CHECK (max_per_hour BETWEEN 1 AND 50),
  expiry_minutes        integer NOT NULL DEFAULT 10 CHECK (expiry_minutes BETWEEN 1 AND 30),
  code_length           integer NOT NULL DEFAULT 6 CHECK (code_length BETWEEN 4 AND 8),
  sms_sender_id         text,
  sms_message_id        text,      -- Bulk9 DLT template (one variable) the code goes into
  wa_template_name      text,      -- approved AUTHENTICATION template on the tenant's WABA
  wa_template_language  text,
  status_webhook_url    text,
  status_webhook_secret text,      -- HMAC key for X-Anril-Signature; shown to the owner once
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- API keys (server-to-server)
-- Only the sha256 of the full key is stored; key_prefix is for display.
CREATE TABLE IF NOT EXISTS otp_api_keys (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key_prefix   text NOT NULL,
  key_hash     text NOT NULL UNIQUE,
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid,
  revoked_at   timestamptz,
  last_used_at timestamptz
);
CREATE INDEX IF NOT EXISTS otp_api_keys_tenant_idx ON otp_api_keys (tenant_id);

-- ---------------------------------------------------------------- one row per code sent
CREATE TABLE IF NOT EXISTS otp_requests (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  phone               text NOT NULL,                 -- digits with country code, e.g. 919876543210
  mode                text NOT NULL CHECK (mode IN ('sms', 'whatsapp', 'both', 'sms_then_whatsapp')),
  source              text NOT NULL CHECK (source IN ('anril', 'client')),
  origin              text NOT NULL CHECK (origin IN ('dashboard', 'api', 'bot', 'telecaller')),
  code_hash           text,                          -- anril-made only
  code_masked         text NOT NULL,
  ref                 text,                          -- client's own reference, echoed in updates
  api_key_id          uuid REFERENCES otp_api_keys(id) ON DELETE SET NULL,
  created_by          uuid,
  status              text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'verified', 'expired', 'locked', 'not_requested', 'failed')),
  attempts            integer NOT NULL DEFAULT 0,
  expires_at          timestamptz NOT NULL,
  verified_at         timestamptz,
  sms_status          text NOT NULL DEFAULT 'none'
                      CHECK (sms_status IN ('none', 'sent', 'delivered', 'failed')),
  sms_request_id      text,
  sms_error           text,
  whatsapp_status     text NOT NULL DEFAULT 'none'
                      CHECK (whatsapp_status IN ('none', 'sent', 'delivered', 'read', 'failed')),
  whatsapp_message_id text,
  whatsapp_error      text,
  fallback_due_at     timestamptz,                   -- sms_then_whatsapp: when WhatsApp goes if no delivery
  fallback_sent_at    timestamptz,                   -- set once, by whoever claims the backup send
  pending_code_enc    text,                          -- AES-GCM copy of the code, ONLY while a WhatsApp
                                                     -- backup may still be due; wiped once it's settled
  not_requested_at    timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS otp_requests_tenant_phone_idx ON otp_requests (tenant_id, phone, created_at DESC);
CREATE INDEX IF NOT EXISTS otp_requests_tenant_created_idx ON otp_requests (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS otp_requests_wamid_idx ON otp_requests (whatsapp_message_id)
  WHERE whatsapp_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS otp_requests_fallback_due_idx ON otp_requests (fallback_due_at)
  WHERE fallback_due_at IS NOT NULL AND fallback_sent_at IS NULL;
CREATE INDEX IF NOT EXISTS otp_requests_pending_expiry_idx ON otp_requests (expires_at)
  WHERE status = 'pending';

-- ---------------------------------------------------------------- status updates outbox
-- One row per event to push to the client's status URL. Retried with back-off by the
-- otp-sweep queue job. The code itself is never in the payload.
CREATE TABLE IF NOT EXISTS otp_status_events (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  otp_id          uuid NOT NULL REFERENCES otp_requests(id) ON DELETE CASCADE,
  event           text NOT NULL,
  payload         jsonb NOT NULL,
  status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'failed')),
  attempts        integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error      text,
  delivered_at    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS otp_status_events_due_idx ON otp_status_events (next_attempt_at)
  WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS otp_status_events_otp_idx ON otp_status_events (otp_id);

-- ---------------------------------------------------------------- RLS + grants
-- Backend service role only. Key hashes, code hashes and the webhook secret must never be
-- readable through PostgREST by a tenant member or anon client.
ALTER TABLE otp_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_status_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON otp_settings FROM anon, authenticated;
REVOKE ALL ON otp_api_keys FROM anon, authenticated;
REVOKE ALL ON otp_requests FROM anon, authenticated;
REVOKE ALL ON otp_status_events FROM anon, authenticated;

-- ---------------------------------------------------------------- atomic code check
-- Locks the row, so parallel guesses can't each see attempts=0: at most 5 wrong tries ever.
-- Returns: verified | wrong_code | locked | expired | not_found | already_verified |
--          not_requested | failed | not_checkable (client-made code: Anril has no hash).
CREATE OR REPLACE FUNCTION otp_try_code(p_tenant uuid, p_id uuid, p_hash text, p_max_attempts integer)
RETURNS text
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  r otp_requests%ROWTYPE;
BEGIN
  SELECT * INTO r FROM otp_requests WHERE id = p_id AND tenant_id = p_tenant FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 'not_found';
  END IF;
  IF r.code_hash IS NULL THEN
    RETURN 'not_checkable';
  END IF;
  IF r.status = 'verified' THEN
    RETURN 'already_verified';
  END IF;
  IF r.status <> 'pending' THEN
    RETURN r.status;   -- expired | locked | not_requested | failed
  END IF;
  IF r.expires_at <= now() THEN
    UPDATE otp_requests SET status = 'expired', fallback_due_at = NULL, pending_code_enc = NULL WHERE id = p_id;
    RETURN 'expired';
  END IF;
  IF r.code_hash = p_hash THEN
    UPDATE otp_requests SET status = 'verified', verified_at = now(), attempts = r.attempts + 1,
                            fallback_due_at = NULL, pending_code_enc = NULL
     WHERE id = p_id;
    RETURN 'verified';
  END IF;
  IF r.attempts + 1 >= p_max_attempts THEN
    UPDATE otp_requests SET status = 'locked', attempts = r.attempts + 1, fallback_due_at = NULL,
                            pending_code_enc = NULL
     WHERE id = p_id;
    RETURN 'locked';
  END IF;
  UPDATE otp_requests SET attempts = r.attempts + 1 WHERE id = p_id;
  RETURN 'wrong_code';
END;
$$;
REVOKE ALL ON FUNCTION otp_try_code(uuid, uuid, text, integer) FROM PUBLIC, anon, authenticated;
