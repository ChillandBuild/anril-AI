-- 235_scheduled_template_sends.sql
-- Schedule a template: staff pick a time instead of sending a template straight away, from the
-- chat, Leads, Telecalling and the New message form. One row per scheduled message; the
-- `scheduled-templates` scheduler job (1 min) sends the due ones. Additive only.
--
-- status: scheduled -> sending -> sent | failed | skipped, or scheduled -> cancelled (and back,
-- for the Undo toast). `sending` is the claim: a conditional scheduled -> sending update means two
-- runs never double-send. A row stuck in `sending` for 15 minutes is marked failed, never re-sent,
-- because Meta may already have delivered it.
--
-- Must be applied BEFORE the backend that reads it is deployed.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS scheduled_template_sends (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- A wiped lead must not get a message later, so its pending rows go with it.
  lead_id       uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  -- The template can be deleted after scheduling; the row then fails at send time with a reason.
  template_id   uuid REFERENCES message_templates(id) ON DELETE SET NULL,
  template_name text NOT NULL,
  variables     jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- The text as the customer will see it: what the chat shows while it waits.
  content       text NOT NULL,
  send_at       timestamptz NOT NULL,
  status        text NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'sending', 'sent', 'failed', 'skipped', 'cancelled')),
  reason        text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  claimed_at    timestamptz,
  sent_at       timestamptz,
  cancelled_at  timestamptz
);

CREATE INDEX IF NOT EXISTS scheduled_template_sends_due_idx
  ON scheduled_template_sends (send_at) WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS scheduled_template_sends_lead_idx
  ON scheduled_template_sends (tenant_id, lead_id, send_at DESC);

-- ---------------------------------------------------------------- RLS
-- Writes come from the backend's service role only; members may read their own tenant's rows.
ALTER TABLE scheduled_template_sends ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS scheduled_template_sends_tenant_member_select ON scheduled_template_sends;
CREATE POLICY scheduled_template_sends_tenant_member_select ON scheduled_template_sends
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
