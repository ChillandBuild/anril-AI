-- 301: WhatsApp Forms, Phase 3 — reach (when a form goes out) and its numbers.
--
-- * whatsapp_form_designs.triggers: when Anril sends the form by itself, all editable:
--     {"ai":         {"enabled": bool, "when": "<the client's own rule, any language>"},
--      "ads":        {"enabled": bool, "ad_ids": [..] (empty = every Click-to-WhatsApp ad), "timing": "instead"|"after"},
--      "broadcasts": {"enabled": bool, "templates": [template names], "timing": "instead"|"after"}}
-- * whatsapp_form_sends: every form that went out (chat, AI, ad, broadcast reply, template
--   button, Services) with the send id inside its signed token, so the form's numbers
--   (sent -> submitted -> paid) are exact, and the same trigger isn't re-sent to one person.

ALTER TABLE whatsapp_form_designs ADD COLUMN IF NOT EXISTS triggers jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS whatsapp_form_sends (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  design_id uuid REFERENCES whatsapp_form_designs(id) ON DELETE SET NULL,  -- NULL = the Services form
  form_id uuid REFERENCES whatsapp_forms(id) ON DELETE SET NULL,
  lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
  via text NOT NULL CHECK (via IN ('chat', 'ai', 'ad', 'broadcast', 'template', 'services')),
  send_id text NOT NULL CHECK (send_id ~ '^[0-9a-f]{12}$'),
  meta_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, send_id)
);
CREATE INDEX IF NOT EXISTS whatsapp_form_sends_design_idx ON whatsapp_form_sends (tenant_id, design_id, created_at DESC);
CREATE INDEX IF NOT EXISTS whatsapp_form_sends_lead_idx ON whatsapp_form_sends (tenant_id, lead_id, created_at DESC);
ALTER TABLE whatsapp_form_sends ENABLE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_form_sends_tenant_member_select ON whatsapp_form_sends
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
