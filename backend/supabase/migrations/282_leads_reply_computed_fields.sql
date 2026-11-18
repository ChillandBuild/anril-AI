-- 282_leads_reply_computed_fields.sql
-- Engage > Inbound leads: "waiting for your reply" and the latest message, answered inside
-- the database so the list can filter, count and sort on them (no id lists in the URL).
-- Two PostgREST computed fields on leads:
--   waiting_since(leads) -> last_inbound_at when nothing was sent to them after it (their
--                           message is the latest one, the same rule as Chats' inbox), else NULL.
--                           Uses idx_messages_lead_outbound_created (lead_id, created_at) WHERE outbound.
--   last_message(leads)  -> {"content","direction","at","ai"} of their newest message, NULL if none.
--                           Selected only for the rows on screen.
-- Both are STABLE SQL and SECURITY INVOKER, so RLS on leads/messages still applies.

CREATE OR REPLACE FUNCTION waiting_since(l leads) RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN l.last_inbound_at IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM messages m
      WHERE m.lead_id = l.id AND m.direction = 'outbound' AND m.created_at > l.last_inbound_at
    ) THEN l.last_inbound_at
  END
$$;

CREATE OR REPLACE FUNCTION last_message(l leads) RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'content', left(m.content, 300),
    'direction', m.direction,
    'at', m.created_at,
    'ai', coalesce(m.is_ai_generated, false)
  )
  FROM messages m
  WHERE m.lead_id = l.id
  ORDER BY m.created_at DESC
  LIMIT 1
$$;
