-- 253: first inbound message per lead, for the Inbound Leads "Keyword" column.
--
-- Why: the route used to fetch EVERY inbound message for the page's leads and
-- keep the first per lead in Python. PostgREST caps a response at 1000 rows
-- (the client's .limit(50000) can't raise it), so once those leads had more
-- than 1000 inbound messages the newest leads lost theirs and showed
-- "no message yet" (Astro Tamil - ORG, 2026-11-09: 1079 messages for 200
-- leads, newest 22 blank). This returns exactly one row per lead.

CREATE OR REPLACE FUNCTION first_inbound_messages(p_tenant uuid, p_lead_ids uuid[])
RETURNS TABLE (lead_id uuid, content text)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public AS $$
  SELECT DISTINCT ON (m.lead_id) m.lead_id, m.content
  FROM messages m
  WHERE m.tenant_id = p_tenant
    AND m.lead_id = ANY (p_lead_ids)
    AND m.direction = 'inbound'
  ORDER BY m.lead_id, m.created_at ASC
$$;

REVOKE EXECUTE ON FUNCTION first_inbound_messages(uuid, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION first_inbound_messages(uuid, uuid[]) TO service_role;
