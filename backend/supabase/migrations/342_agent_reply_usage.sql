-- 342_agent_reply_usage.sql
-- Agents billing (23 Nov 2026): every finished reply of a business's AI agent (public /chat, /widget/chat and
-- their /continue) adds 1 to the monthly counter 'agent_reply'. The operator sets each client's included
-- replies and monthly price on the item 'agent_replies' (hidden from the client's plan cart, like
-- private_send). Track only: going over never blocks a reply.
-- Undo: undo/342_agent_reply_usage_undo.sql
SET LOCAL lock_timeout = '5s';

-- Same list as 218_private_send.sql plus 'agent_reply'.
ALTER TABLE tenant_usage_counters DROP CONSTRAINT IF EXISTS tenant_usage_counters_metric_check;
ALTER TABLE tenant_usage_counters ADD CONSTRAINT tenant_usage_counters_metric_check
  CHECK (metric IN (
    'message_sent', 'ai_reply', 'call_minute', 'team_seat_active', 'storage_gb',
    'ai_call_summary', 'ai_call_scoring', 'phone_number',
    'ai_speech_to_text', 'ai_text_to_speech',
    'private_send_message', 'agent_reply'
  ));

-- Category ai / pillar shared, like the AI tiers (feature_catalog_category_check). One included reply per unit: the client's item quantity IS its included replies, and
-- unit_price_snapshot = monthly price / quantity (so quantity x snapshot = the monthly price, as for every item).
INSERT INTO feature_catalog (feature_key, display_name, category, pillar, monthly_price, usage_metric, unit_price, included_qty, depends_on, is_metered, sort_order)
VALUES ('agent_replies', 'Agent replies', 'ai', 'shared', 0, 'agent_reply', 0, 1, '{}', true, 109)
ON CONFLICT (feature_key) DO NOTHING;

-- Atomic +delta. The Python read-modify-write (entitlements.increment_usage) loses counts when replies land
-- at the same moment; an agent can answer several people per second. p_included is used only when the
-- period's row does not exist yet. Returns the new used.
CREATE OR REPLACE FUNCTION public.add_usage(p_tenant uuid, p_period text, p_metric text, p_delta integer,
                                            p_included integer)
RETURNS numeric
LANGUAGE sql
SECURITY INVOKER
SET search_path = public
AS $$
  INSERT INTO tenant_usage_counters AS c (tenant_id, period, metric, used, included)
  VALUES (p_tenant, p_period, p_metric, GREATEST(p_delta, 0), GREATEST(p_included, 0))
  ON CONFLICT (tenant_id, period, metric) DO UPDATE SET used = c.used + GREATEST(p_delta, 0)
  RETURNING used;
$$;

REVOKE EXECUTE ON FUNCTION public.add_usage(uuid, text, text, integer, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.add_usage(uuid, text, text, integer, integer) TO service_role;
