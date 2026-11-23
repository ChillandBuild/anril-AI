-- 320_reports_customers_forms.sql
-- v9.2 Batch H: #16 Reports, #17 Customers, #18 Meta Instant-form leads (Prem: "Yes, build all three", 2026-11-23).
--
-- Customers:
--   lead_tags            plain-word tags on a person (max 10 per person, enforced in code).
--   customer_feedback    one star request per order (delivered) or booking (came); stars, reason, fixed.
--                        Feedback on/off and the thank-you offer live in app_settings (feedback_on, feedback_offer).
--   reengagement_steps.target_group_id   a follow-up can target one Customers group.
-- Meta Instant forms:
--   meta_form_leads.delivery_status      what Meta's receipts said about the form template we sent
--                                        (template_status stays 'sent'; this column adds delivered / read /
--                                        failed / no_whatsapp). sent_to_calling_at = handed to Call IQ.
--   meta_lead_forms.auto_hello           a form with no template chosen uses the ready-made form_lead_hello.
-- Reports:
--   analytics_response_times_split()     reply times split by who answered first: the AI agent or a person.
--
-- New tables: RLS on, no member policies (service key only). Additive. Undo: undo/320_reports_customers_forms_undo.sql
SET LOCAL lock_timeout = '5s';

-- ── Customers: tags ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.lead_tags (
  tenant_id   uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  lead_id     uuid NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  tag         text NOT NULL CHECK (length(btrim(tag)) BETWEEN 1 AND 30 AND tag = btrim(tag)),
  created_by  uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lead_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_lead_tags_tenant_tag ON public.lead_tags (tenant_id, lower(tag));
CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_tags_lead_lower ON public.lead_tags (lead_id, lower(tag));  -- "VIP" = "vip"

-- ── Customers: feedback ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.customer_feedback (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  lead_id          uuid REFERENCES public.leads(id) ON DELETE SET NULL,
  phone            text NOT NULL CHECK (length(phone) BETWEEN 6 AND 20),
  kind             text NOT NULL CHECK (kind IN ('order', 'booking')),
  deal_id          uuid REFERENCES public.deals(id) ON DELETE SET NULL,
  booking_id       uuid REFERENCES public.bookings(id) ON DELETE SET NULL,
  staff_user_id    uuid,
  staff_name       text CHECK (staff_name IS NULL OR length(staff_name) <= 80),
  status           text NOT NULL DEFAULT 'asked'
                   CHECK (status IN ('asked', 'answered', 'fixed', 'failed')),
  asked_at         timestamptz NOT NULL DEFAULT now(),
  ask_message_id   text,
  stars            integer CHECK (stars IS NULL OR stars BETWEEN 1 AND 5),
  answered_at      timestamptz,
  reason           text CHECK (reason IS NULL OR length(reason) <= 500),
  reason_at        timestamptz,
  fixed_by         uuid,
  fixed_at         timestamptz,
  error            text CHECK (error IS NULL OR length(error) <= 300),
  created_at       timestamptz NOT NULL DEFAULT now()
);
-- Never ask twice for the same order or booking.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_feedback_deal ON public.customer_feedback (deal_id) WHERE deal_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_feedback_booking ON public.customer_feedback (booking_id) WHERE booking_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_customer_feedback_tenant ON public.customer_feedback (tenant_id, asked_at DESC);
CREATE INDEX IF NOT EXISTS idx_customer_feedback_phone ON public.customer_feedback (tenant_id, phone, asked_at DESC);

-- ── Engage follow-ups: target a Customers group ─────────────────────────────
ALTER TABLE public.reengagement_steps
  ADD COLUMN IF NOT EXISTS target_group_id uuid REFERENCES public.customer_groups(id) ON DELETE SET NULL;

-- ── Meta Instant forms ──────────────────────────────────────────────────────
ALTER TABLE public.meta_form_leads
  ADD COLUMN IF NOT EXISTS delivery_status text
    CHECK (delivery_status IS NULL OR delivery_status IN ('delivered', 'read', 'failed', 'no_whatsapp')),
  ADD COLUMN IF NOT EXISTS delivery_updated_at timestamptz,
  ADD COLUMN IF NOT EXISTS sent_to_calling_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_meta_form_leads_template_msg
  ON public.meta_form_leads (template_message_id) WHERE template_message_id IS NOT NULL;

ALTER TABLE public.meta_lead_forms
  ADD COLUMN IF NOT EXISTS auto_hello boolean NOT NULL DEFAULT true;

-- ── Reports: reply times, AI agent vs a person ──────────────────────────────
-- Same pairing as analytics_response_times (158): each inbound message and the first outbound after it.
-- who = 'ai' when that first outbound was written by the AI agent, else 'staff'.
CREATE OR REPLACE FUNCTION public.analytics_response_times_split(
  p_tenant_id uuid,
  p_start timestamptz,
  p_end timestamptz
)
RETURNS TABLE (
  who text,
  answered bigint,
  p50_seconds numeric,
  p90_seconds numeric
)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  WITH pairs AS (
    SELECT r.out_at, r.out_ai, m.created_at AS in_at
    FROM messages m
    CROSS JOIN LATERAL (
      SELECT o.created_at AS out_at, coalesce(o.is_ai_generated, false) AS out_ai
      FROM messages o
      WHERE o.lead_id = m.lead_id
        AND o.direction = 'outbound'
        AND o.created_at > m.created_at
      ORDER BY o.created_at
      LIMIT 1
    ) r
    WHERE m.tenant_id = p_tenant_id
      AND m.direction = 'inbound'
      AND m.lead_id IS NOT NULL
      AND m.created_at >= p_start
      AND m.created_at <  p_end
  )
  SELECT
    CASE WHEN out_ai THEN 'ai' ELSE 'staff' END                                       AS who,
    count(*)                                                                          AS answered,
    round(percentile_cont(0.5) WITHIN GROUP (
      ORDER BY extract(epoch FROM (out_at - in_at)))::numeric, 1)                     AS p50_seconds,
    round(percentile_cont(0.9) WITHIN GROUP (
      ORDER BY extract(epoch FROM (out_at - in_at)))::numeric, 1)                     AS p90_seconds
  FROM pairs
  GROUP BY 1;
$$;
REVOKE EXECUTE ON FUNCTION public.analytics_response_times_split(uuid, timestamptz, timestamptz) FROM PUBLIC, anon, authenticated;

-- ── RLS: service key only ───────────────────────────────────────────────────
ALTER TABLE public.lead_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_feedback ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.lead_tags IS 'Customers › tags. Plain words, max 10 per person (code). Service key only.';
COMMENT ON TABLE public.customer_feedback IS
  'Customers › Feedback. One star ask per delivered order or Came booking; never to Said stop. Service key only.';
