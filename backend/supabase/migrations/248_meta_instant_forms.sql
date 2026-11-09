-- 248_meta_instant_forms.sql
-- Meta Instant Forms (lead ads): the Page's forms, each submission with every answer,
-- and the per-form WhatsApp template that goes out the moment a lead arrives.
-- A submission also becomes (or is merged into) a normal lead with source 'meta_form'.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS meta_lead_forms (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  page_id             text NOT NULL,
  form_id             text NOT NULL CHECK (form_id ~ '^[0-9]{1,30}$'),
  name                text NOT NULL DEFAULT '',
  status              text,
  locale              text,
  questions           jsonb NOT NULL DEFAULT '[]'::jsonb,
  meta_created_at     timestamptz,
  -- message_templates.id; NULL = send nothing for this form.
  template_id         uuid REFERENCES message_templates(id) ON DELETE SET NULL,
  -- One entry per template blank, in order: {"source":"field","field":"full_name"} or {"source":"text","text":"..."}.
  template_variables  jsonb NOT NULL DEFAULT '[]'::jsonb,
  synced_at           timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, form_id)
);

CREATE TABLE IF NOT EXISTS meta_form_leads (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  leadgen_id            text NOT NULL CHECK (leadgen_id ~ '^[0-9]{1,30}$'),
  page_id               text NOT NULL,
  form_id               text NOT NULL,
  ad_id                 text,
  ad_name               text,
  adset_id              text,
  adset_name            text,
  campaign_id           text,
  campaign_name         text,
  platform              text,
  is_organic            boolean NOT NULL DEFAULT false,
  meta_created_at       timestamptz NOT NULL,
  -- Meta's field_data as returned: [{"name": "full_name", "values": ["Priya"]}, ...]
  answers               jsonb NOT NULL DEFAULT '[]'::jsonb,
  name                  text,
  phone                 text,
  email                 text,
  lead_id               uuid REFERENCES leads(id) ON DELETE SET NULL,
  -- How Anril learned of it: the live webhook, the catch-up check, or the first import.
  received_via          text NOT NULL DEFAULT 'webhook' CHECK (received_via IN ('webhook', 'catch_up', 'import')),
  template_status       text NOT NULL DEFAULT 'pending'
                        CHECK (template_status IN ('pending', 'sending', 'sent', 'failed', 'no_template', 'no_phone', 'skipped_old')),
  template_error        text,
  template_message_id   text,
  template_sent_at      timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, leadgen_id)
);

CREATE INDEX IF NOT EXISTS meta_form_leads_form_idx ON meta_form_leads (tenant_id, form_id, meta_created_at DESC);
CREATE INDEX IF NOT EXISTS meta_form_leads_lead_idx ON meta_form_leads (lead_id);

ALTER TABLE meta_lead_forms ENABLE ROW LEVEL SECURITY;
ALTER TABLE meta_form_leads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON meta_lead_forms, meta_form_leads FROM anon, authenticated;
GRANT ALL ON meta_lead_forms, meta_form_leads TO service_role;
-- No member policies: clients read these through /api/v1/instant-forms only.

-- A form lead is a lead like any other, tagged with its own source.
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_source_check;
ALTER TABLE leads ADD CONSTRAINT leads_source_check CHECK (source = ANY (ARRAY[
  'whatsapp', 'instagram', 'upload', 'manual', 'telegram', 'facebook', 'indiamart', 'justdial',
  'website', 'api', 'store', 'meta_form'
]));
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_opt_in_source_check;
ALTER TABLE leads ADD CONSTRAINT leads_opt_in_source_check CHECK (opt_in_source = ANY (ARRAY[
  'click_to_wa_ad', 'website_form', 'offline_event', 'previous_enquiry', 'imported', 'manual', 'whatsapp',
  'instagram', 'facebook', 'telegram', 'csv', 'indiamart', 'justdial', 'api', 'meta_form'
]));
