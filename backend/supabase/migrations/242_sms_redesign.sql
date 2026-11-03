-- 242_sms_redesign.sql
-- Tables behind the redesigned SMS pages (docs/plans/2026-11-03-sms-redesign.md).
--
-- - sms_dlt_submissions: entities and sender IDs a client submitted from Anril. Bulk9 has no
--   entity list and lists only approved senders, so DLT Setup shows these as "Submitted" until
--   the same ID shows up on an approved sender/template.
-- - sms_pe_tm: PE-TM binding per entity. The client uploads the binding-request screenshot
--   (proof_path in the private sms-dlt bucket), the operator marks TM approved, then the client
--   confirms the final approval. The first entity with both done turns the tenant's
--   app_settings.sms_checklist.pe_tm on (done in the API, not here).
-- - sms_credit_requests: "Add credit" requests the operator fulfils in the reseller panel.
--
-- Service role only, like 237/239/240.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS sms_dlt_submissions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('entity', 'sender')),
  entity_id   text NOT NULL CHECK (entity_id ~ '^[0-9]{5,30}$'),
  entity_name text CHECK (entity_name IS NULL OR length(entity_name) <= 200),
  sender_id   text CHECK (sender_id IS NULL OR sender_id ~ '^[A-Z0-9]{3,6}$'),
  created_by  uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'sender') = (sender_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_dlt_submissions_uq
  ON sms_dlt_submissions (tenant_id, kind, entity_id, coalesce(sender_id, ''));

CREATE TABLE IF NOT EXISTS sms_pe_tm (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  entity_id       text NOT NULL CHECK (entity_id ~ '^[0-9]{5,30}$'),
  proof_path      text NOT NULL,
  tm_approved_at  timestamptz,
  tm_approved_by  uuid,
  pe_confirmed_at timestamptz,
  pe_confirmed_by uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, entity_id),
  CHECK (pe_confirmed_at IS NULL OR tm_approved_at IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS sms_credit_requests (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  amount       numeric(12, 2) NOT NULL CHECK (amount BETWEEN 100 AND 1000000),
  note         text CHECK (note IS NULL OR length(note) <= 300),
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
  requested_by uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  done_at      timestamptz,
  done_by      uuid
);
CREATE INDEX IF NOT EXISTS sms_credit_requests_tenant_idx ON sms_credit_requests (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS sms_credit_requests_open_idx ON sms_credit_requests (created_at DESC) WHERE status = 'open';

ALTER TABLE sms_dlt_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_pe_tm ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_credit_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sms_dlt_submissions, sms_pe_tm, sms_credit_requests FROM anon, authenticated;
GRANT ALL ON sms_dlt_submissions, sms_pe_tm, sms_credit_requests TO service_role;
