-- 297: WhatsApp Forms (Meta Flows) for Services intake, plus one consent record per lead.
--
-- * whatsapp_forms: every version of a form Anril published to Meta. Published Meta forms
--   cannot be edited, so a Services save that changes packages or details publishes a NEW row
--   and the old one becomes 'retired' (kept: a customer may still submit an old form, and
--   its token and answer map must still be readable).
-- * whatsapp_form_responses: one row per submitted form (deduped on Meta's message id AND on the
--   sent form's token, so reopening an old form after paying can't book and charge twice).
-- * lead_consents: what a lead agreed to, where, with the exact wording and time. Scope
--   'replies' = answers about what they asked for; 'offers' = marketing broadcasts.
--   Shared by WhatsApp Forms now and the Meta lead-form consent fix next.

CREATE TABLE IF NOT EXISTS whatsapp_forms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL DEFAULT 'intake' CHECK (kind IN ('intake', 'custom')),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  status text NOT NULL DEFAULT 'publishing'
    CHECK (status IN ('publishing', 'published', 'failed', 'retired')),
  meta_flow_id text,
  meta_waba_id text,
  source_hash text NOT NULL,
  definition jsonb NOT NULL,      -- the Flow JSON sent to Meta
  answer_map jsonb NOT NULL,      -- form field names -> package / add-on / detail keys
  last_error text,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS whatsapp_forms_tenant_kind_idx ON whatsapp_forms (tenant_id, kind, created_at DESC);
ALTER TABLE whatsapp_forms ENABLE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_forms_tenant_member_select ON whatsapp_forms
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS whatsapp_form_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  form_id uuid REFERENCES whatsapp_forms(id) ON DELETE SET NULL,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  meta_message_id text NOT NULL,
  flow_token text,                -- set only when verified; one sent form = one submission
  answers jsonb NOT NULL DEFAULT '{}'::jsonb,
  outcome text NOT NULL DEFAULT 'received'
    CHECK (outcome IN ('received', 'link_sent', 'continued_in_chat', 'rejected')),
  intake_session_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, meta_message_id),
  UNIQUE (tenant_id, flow_token)
);
CREATE INDEX IF NOT EXISTS whatsapp_form_responses_form_idx ON whatsapp_form_responses (tenant_id, form_id, created_at DESC);
CREATE INDEX IF NOT EXISTS whatsapp_form_responses_lead_idx ON whatsapp_form_responses (lead_id);
ALTER TABLE whatsapp_form_responses ENABLE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_form_responses_tenant_member_select ON whatsapp_form_responses
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS lead_consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  scope text NOT NULL CHECK (scope IN ('replies', 'offers')),
  granted boolean NOT NULL,
  source text NOT NULL CHECK (length(source) BETWEEN 1 AND 120),
  wording text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lead_consents_lead_idx ON lead_consents (tenant_id, lead_id, scope, created_at DESC);
ALTER TABLE lead_consents ENABLE ROW LEVEL SECURITY;
CREATE POLICY lead_consents_tenant_member_select ON lead_consents
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
