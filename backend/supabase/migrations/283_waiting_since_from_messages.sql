-- 283_waiting_since_from_messages.sql
-- Fixes waiting_since(leads) from 282. leads.last_inbound_at is stamped AFTER the AI
-- reply is saved (checked live 2026-11-18: message 13:47:43, AI reply 13:47:52,
-- last_inbound_at 13:47:53), so comparing outbound messages with it showed answered chats
-- as waiting. Now read from messages only: waiting = an inbound message with nothing sent
-- after it; the wait counts from the first unanswered inbound message.
-- max(outbound) uses idx_messages_lead_outbound_created; the inbound scan uses idx_messages_lead_id.

CREATE OR REPLACE FUNCTION waiting_since(l leads) RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT min(m.created_at)
  FROM messages m
  WHERE m.lead_id = l.id
    AND m.direction = 'inbound'
    AND m.created_at > coalesce(
      (SELECT max(o.created_at) FROM messages o WHERE o.lead_id = l.id AND o.direction = 'outbound'),
      '-infinity'::timestamptz)
$$;
