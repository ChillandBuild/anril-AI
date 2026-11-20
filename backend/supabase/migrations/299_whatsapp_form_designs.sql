-- 299: WhatsApp Forms, Phase 2 — the client's own forms (Catalogue → Forms).
--
-- * whatsapp_form_designs: the editable form: name, language (en | ta | tanglish), questions
--   and every text it shows (overrides on top of the language's starting texts). Nothing in
--   the form's wording is fixed in code. Archived forms stay for their answers' history.
-- * whatsapp_forms.design_id: which design a published version came from (kind 'custom').
-- * whatsapp_form_responses outcome 'saved': a custom form's answers saved on the lead.

CREATE TABLE IF NOT EXISTS whatsapp_form_designs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'ta', 'tanglish')),
  fields jsonb NOT NULL DEFAULT '[]'::jsonb,
  texts jsonb NOT NULL DEFAULT '{}'::jsonb,
  archived boolean NOT NULL DEFAULT false,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS whatsapp_form_designs_tenant_idx ON whatsapp_form_designs (tenant_id, archived, created_at DESC);
ALTER TABLE whatsapp_form_designs ENABLE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_form_designs_tenant_member_select ON whatsapp_form_designs
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE whatsapp_forms ADD COLUMN IF NOT EXISTS design_id uuid REFERENCES whatsapp_form_designs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS whatsapp_forms_design_idx ON whatsapp_forms (tenant_id, design_id, created_at DESC);

ALTER TABLE whatsapp_form_responses DROP CONSTRAINT IF EXISTS whatsapp_form_responses_outcome_check;
ALTER TABLE whatsapp_form_responses ADD CONSTRAINT whatsapp_form_responses_outcome_check
  CHECK (outcome IN ('received', 'link_sent', 'continued_in_chat', 'rejected', 'saved'));
