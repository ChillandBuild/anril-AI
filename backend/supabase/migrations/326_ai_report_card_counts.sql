-- 326: the AI report card counted inside the database (Anril Setup).
-- Before this, the report card read every message and handover of the period into the server and counted
-- there; a busy business with 90 days picked paid for it in time. This function returns the same four
-- numbers (chats, handled alone, handed to a person, handed over for a missing answer) in one round trip.
-- It mirrors services/brain/headline.aggregate + services/brain/handovers.classify_reason, so the numbers
-- must not change. Service role only: the backend is the only caller.
CREATE OR REPLACE FUNCTION public.ai_report_card_counts(p_tenant_id uuid, p_start timestamptz, p_end timestamptz)
RETURNS TABLE (chats bigint, handled_alone bigint, handed_over bigint, knowledge_gaps bigint)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  WITH inbound AS (
    SELECT DISTINCT m.lead_id FROM public.messages m
    WHERE m.tenant_id = p_tenant_id AND m.created_at >= p_start AND m.created_at < p_end
      AND m.direction = 'inbound' AND m.lead_id IS NOT NULL
  ),
  answered AS (
    SELECT DISTINCT m.lead_id FROM public.messages m
    WHERE m.tenant_id = p_tenant_id AND m.created_at >= p_start AND m.created_at < p_end
      AND m.direction = 'outbound' AND m.is_ai_generated IS TRUE
      AND m.reply_source IN ('ai', 'knowledge') AND m.lead_id IS NOT NULL
  ),
  -- one row per chat that was handed over, under its most telling reason:
  -- 1 asked for a person, 2 missing answer, 3 payment link, 4 other
  handed AS (
    SELECT h.lead_id,
           MIN(CASE
                 WHEN btrim(h.reason) = 'User requested a human agent' THEN 1
                 WHEN btrim(h.reason) IN (
                   'Anril told the customer it is checking with the team',
                   'Aira told the customer it is checking with the team',
                   'AI failed to generate a response',
                   'AI gave a generic fallback reply',
                   'AI indicated team will follow up') THEN 2
                 WHEN lower(btrim(h.reason)) LIKE 'payment link could not be created%' THEN 3
                 ELSE 4
               END) AS top_kind
    FROM public.chat_handovers h
    JOIN inbound i ON i.lead_id = h.lead_id
    WHERE h.tenant_id = p_tenant_id AND h.opened_at >= p_start AND h.opened_at < p_end
    GROUP BY h.lead_id
  )
  SELECT
    (SELECT count(*) FROM inbound),
    (SELECT count(*) FROM inbound i JOIN answered a ON a.lead_id = i.lead_id
       WHERE NOT EXISTS (SELECT 1 FROM handed x WHERE x.lead_id = i.lead_id)),
    (SELECT count(*) FROM handed),
    (SELECT count(*) FROM handed WHERE top_kind = 2);
$$;

REVOKE ALL ON FUNCTION public.ai_report_card_counts(uuid, timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ai_report_card_counts(uuid, timestamptz, timestamptz) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_report_card_counts(uuid, timestamptz, timestamptz) TO service_role;
