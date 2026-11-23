-- 323_alerts_automations.sql  (v9.2 #26 Alerts & automations)
-- Two new tables, additive only. RLS on, no policies: the backend uses the service key.
--   automation_pauses     why an automation was paused when WhatsApp turned its template down or paused it.
--                         resumed_at stays NULL while it is paused; when the template is approved again only the
--                         rows this log shows as switched off by Anril are switched back on.
--   comeback_offer_sends  every Come-back offer message, so "at most 1 per customer per 30 days" holds.
-- The Evening summary and Come-back offer settings are app_settings rows (evening_summary, comeback_offer): no table.
-- Undo: undo/323_alerts_automations_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.automation_pauses (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  automation_key  text NOT NULL CHECK (length(automation_key) BETWEEN 1 AND 120),
  automation_name text,
  template_name   text NOT NULL,
  reason          text NOT NULL CHECK (length(reason) <= 300),
  switched_off    boolean NOT NULL DEFAULT false,
  paused_at       timestamptz NOT NULL DEFAULT now(),
  resumed_at      timestamptz
);
-- One open pause per automation and template.
CREATE UNIQUE INDEX IF NOT EXISTS uq_automation_pauses_open
  ON public.automation_pauses (tenant_id, automation_key, template_name) WHERE resumed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_automation_pauses_tenant_open
  ON public.automation_pauses (tenant_id) WHERE resumed_at IS NULL;

CREATE TABLE IF NOT EXISTS public.comeback_offer_sends (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  lead_id       uuid NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  phone         text NOT NULL,
  template_name text NOT NULL,
  status        text NOT NULL DEFAULT 'sending' CHECK (status IN ('sending', 'sent', 'failed')),
  error         text CHECK (error IS NULL OR length(error) <= 300),
  created_at    timestamptz NOT NULL DEFAULT now(),
  sent_at       timestamptz
);
CREATE INDEX IF NOT EXISTS idx_comeback_sends_lead
  ON public.comeback_offer_sends (tenant_id, lead_id, created_at DESC);

ALTER TABLE public.automation_pauses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comeback_offer_sends ENABLE ROW LEVEL SECURITY;
