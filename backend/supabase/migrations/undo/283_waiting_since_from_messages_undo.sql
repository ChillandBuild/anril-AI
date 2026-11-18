-- Undo 283: back to 282's waiting_since (compares with leads.last_inbound_at).
CREATE OR REPLACE FUNCTION waiting_since(l leads) RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN l.last_inbound_at IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM messages m
      WHERE m.lead_id = l.id AND m.direction = 'outbound' AND m.created_at > l.last_inbound_at
    ) THEN l.last_inbound_at
  END
$$;
