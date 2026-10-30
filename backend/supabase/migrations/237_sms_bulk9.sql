-- 237_sms_bulk9.sql
-- SMS through Bulk9 (Fast2SMS white-label). Clients send DLT SMS campaigns to their leads from
-- /dashboard/sms; Anril's server calls Bulk9 with the client's own key (app_settings
-- bulk9_api_key). Plan: docs/plans/2026-10-30-bulk9-sms-full-build.md. Additive only.
--
-- sms_messages.status: queued -> sending -> submitted -> delivered | failed, or
-- queued -> skipped | cancelled. `sending` is the claim (conditional queued -> sending update, so
-- two scheduler runs never double-send). A timeout after Bulk9 may have accepted the SMS becomes
-- `unknown`: reconciled from delivery reports, never re-sent automatically.
--
-- Writes come from the backend's service role only; members may read their own tenant's rows.
-- Must be applied BEFORE the backend that reads it is deployed.

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------- leads: SMS consent
-- Promotional SMS needs recorded consent (source + time). A WhatsApp opt-in is not SMS consent.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sms_consent_source text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sms_consent_at timestamptz;

-- ---------------------------------------------------------------- templates (cache of Bulk9)
-- `ready` rows come from Bulk9's DLT Manager list (they carry message_id, needed to send).
-- `submitted` rows were added from Anril and are not listed by Bulk9 yet.
CREATE TABLE IF NOT EXISTS sms_templates (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  message_id      text,
  dlt_template_id text,
  sender_id       text NOT NULL,
  entity_id       text,
  entity_name     text,
  message         text NOT NULL,
  var_count       int NOT NULL DEFAULT 0,
  template_type   text NOT NULL DEFAULT 'service' CHECK (template_type IN ('service', 'promotional')),
  status          text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'submitted')),
  last_synced_at  timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_templates_message_uq
  ON sms_templates (tenant_id, message_id) WHERE message_id IS NOT NULL;

-- ---------------------------------------------------------------- template requests
-- "Request a template": the client writes the wording; Prem does the DLT portal work.
CREATE TABLE IF NOT EXISTS sms_template_requests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  wording       text NOT NULL,
  template_type text NOT NULL DEFAULT 'service' CHECK (template_type IN ('service', 'promotional')),
  status        text NOT NULL DEFAULT 'requested'
                CHECK (status IN ('requested', 'in_progress', 'ready', 'rejected')),
  reason        text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sms_template_requests_tenant_idx
  ON sms_template_requests (tenant_id, created_at DESC);

-- ---------------------------------------------------------------- campaigns
CREATE TABLE IF NOT EXISTS sms_campaigns (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name          text NOT NULL,
  template_id   uuid REFERENCES sms_templates(id) ON DELETE SET NULL,
  sender_id     text NOT NULL,
  message_id    text NOT NULL,
  template_type text NOT NULL CHECK (template_type IN ('service', 'promotional')),
  template_text text NOT NULL,
  variable_map  jsonb NOT NULL DEFAULT '[]'::jsonb,
  status        text NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'sending', 'completed', 'cancelled')),
  send_at       timestamptz NOT NULL DEFAULT now(),
  -- Double-clicking Send carries the same key twice; the second insert is refused.
  idempotency_key text NOT NULL,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz,
  cancelled_at  timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_campaigns_idem_uq ON sms_campaigns (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS sms_campaigns_tenant_idx ON sms_campaigns (tenant_id, created_at DESC);

-- ---------------------------------------------------------------- messages (one per recipient)
CREATE TABLE IF NOT EXISTS sms_messages (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  campaign_id      uuid REFERENCES sms_campaigns(id) ON DELETE CASCADE,
  lead_id          uuid REFERENCES leads(id) ON DELETE SET NULL,
  phone            text NOT NULL,
  variables        jsonb NOT NULL DEFAULT '[]'::jsonb,
  content          text NOT NULL,
  send_at          timestamptz NOT NULL DEFAULT now(),
  status           text NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued', 'sending', 'submitted', 'delivered', 'failed',
                                     'unknown', 'skipped', 'cancelled')),
  request_id       text,
  provider_status  text,
  failure_reason   text,
  sms_count        int,
  -- estimated before sending; charged = what Bulk9 debited the client (sms_details);
  -- cost = sms_count x Prem's buy rate at send time (profit = charged - cost).
  estimated_amount numeric(12, 4),
  charged_amount   numeric(12, 4),
  cost_amount      numeric(12, 4),
  claimed_at       timestamptz,
  submitted_at     timestamptz,
  delivered_at     timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sms_messages_due_idx ON sms_messages (send_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS sms_messages_unresolved_idx
  ON sms_messages (submitted_at) WHERE status IN ('submitted', 'unknown');
CREATE INDEX IF NOT EXISTS sms_messages_request_idx ON sms_messages (tenant_id, request_id);
CREATE INDEX IF NOT EXISTS sms_messages_campaign_idx ON sms_messages (campaign_id, status);
CREATE INDEX IF NOT EXISTS sms_messages_tenant_idx ON sms_messages (tenant_id, created_at DESC);

-- ---------------------------------------------------------------- credit ledger
-- Every SMS credit added to or taken from a client's Bulk9 wallet, with both prices.
CREATE TABLE IF NOT EXISTS sms_ledger (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('recharge', 'manual_credit', 'bonus', 'debit')),
  sms_count     int NOT NULL,
  price_per_sms numeric(10, 4) NOT NULL,
  buy_rate      numeric(10, 4),
  amount        numeric(12, 2) NOT NULL,
  expiry_date   date,
  reference     text,
  note          text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sms_ledger_tenant_idx ON sms_ledger (tenant_id, created_at DESC);

-- ---------------------------------------------------------------- Razorpay recharges
-- Paid into Anril's own Razorpay account. status: created -> paid -> credited | credit_failed,
-- or created -> expired | cancelled. One payment id credits once (unique index).
CREATE TABLE IF NOT EXISTS sms_payments (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  amount_paise        int NOT NULL CHECK (amount_paise > 0),
  sms_count           int NOT NULL CHECK (sms_count > 0),
  price_per_sms       numeric(10, 4) NOT NULL,
  razorpay_link_id    text UNIQUE,
  razorpay_payment_id text UNIQUE,
  short_url           text,
  status              text NOT NULL DEFAULT 'created'
                      CHECK (status IN ('created', 'paid', 'credited', 'credit_failed', 'amount_mismatch',
                                        'expired', 'cancelled')),
  error               text,
  created_by          uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  paid_at             timestamptz,
  credited_at         timestamptz
);
CREATE INDEX IF NOT EXISTS sms_payments_tenant_idx ON sms_payments (tenant_id, created_at DESC);

-- ---------------------------------------------------------------- delivery callbacks
-- Every Bulk9 callback, kept for dedupe and for ones that arrive before their send is recorded.
CREATE TABLE IF NOT EXISTS sms_delivery_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  request_id  text,
  phone       text,
  status      text,
  dedupe_key  text NOT NULL,
  matched     boolean NOT NULL DEFAULT false,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_delivery_events_dedupe_uq ON sms_delivery_events (tenant_id, dedupe_key);
CREATE INDEX IF NOT EXISTS sms_delivery_events_unmatched_idx
  ON sms_delivery_events (received_at) WHERE matched = false;

-- ---------------------------------------------------------------- RLS
ALTER TABLE sms_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_template_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_delivery_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sms_templates', 'sms_template_requests', 'sms_campaigns'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_tenant_member_select', t);
    EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (is_tenant_member(tenant_id))',
                   t || '_tenant_member_select', t);
  END LOOP;
END $$;
-- Backend only (no member policy), read through the API which picks safe columns:
-- sms_messages (cost_amount) and sms_ledger (buy_rate) carry Anril's margin, sms_payments.error
-- can carry reseller stock text, sms_delivery_events holds raw provider payloads.

-- ---------------------------------------------------------------- DLT upload bucket
-- Proof files and DLT Excel exports. Private: Bulk9 fetches each through a short-lived signed
-- URL (its add_* endpoints take HTTPS links, not file bodies). Backend service role only.
insert into storage.buckets (id, name, public)
values ('sms-dlt', 'sms-dlt', false)
on conflict (id) do nothing;
