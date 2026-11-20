-- 303_client_claude.sql
-- Anril AI: the client connector at /client/mcp (docs/specs/anril-client-mcp.md).
--   tenant_mcp_connections: one row per (client, owner, approved app). Created when the owner
--     clicks Allow on the consent screen; only a row with status 'active' lets the connector
--     answer, so flipping it to 'revoked' is the owner's off switch.
--   claude_send_days: how many customer messages a client sent through the connector on one
--     Indian-time day. claude_reserve_sends adds to it only while the day's total stays under
--     the cap, in one statement, so two sends at the same moment cannot both slip under it.
-- RLS on with no policies: only the backend's service key can read or write either table.
-- Additive. Apply BEFORE MCP_CLIENT_ENABLED is switched on.
-- Undo: undo/303_client_claude_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.tenant_mcp_connections (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id      uuid NOT NULL,
  client_id    text NOT NULL,
  label        text,
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at   timestamptz,
  UNIQUE (tenant_id, user_id, client_id)
);
ALTER TABLE public.tenant_mcp_connections ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.tenant_mcp_connections IS
  'Anril AI connector: which owner allowed which app for which client. status=active is the on switch. Service key only.';

CREATE TABLE IF NOT EXISTS public.claude_send_days (
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  day       date NOT NULL,
  sent      integer NOT NULL DEFAULT 0 CHECK (sent >= 0),
  PRIMARY KEY (tenant_id, day)
);
ALTER TABLE public.claude_send_days ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.claude_send_days IS
  'Anril AI connector: customer messages sent through the connector per client per IST day. Service key only.';

-- Returns the day's new total, or NULL when adding p_count would pass p_cap (nothing is added).
CREATE OR REPLACE FUNCTION public.claude_reserve_sends(
  p_tenant_id uuid, p_day date, p_count integer, p_cap integer
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_sent integer;
BEGIN
  IF p_count IS NULL OR p_count <= 0 THEN
    RAISE EXCEPTION 'p_count must be positive';
  END IF;
  INSERT INTO public.claude_send_days (tenant_id, day, sent)
  VALUES (p_tenant_id, p_day, 0)
  ON CONFLICT (tenant_id, day) DO NOTHING;
  UPDATE public.claude_send_days
     SET sent = sent + p_count
   WHERE tenant_id = p_tenant_id AND day = p_day AND sent + p_count <= p_cap
  RETURNING sent INTO v_sent;
  RETURN v_sent;
END;
$$;

-- Gives back messages that were reserved but never left (a send that failed before sending).
CREATE OR REPLACE FUNCTION public.claude_release_sends(
  p_tenant_id uuid, p_day date, p_count integer
) RETURNS integer
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.claude_send_days
     SET sent = GREATEST(sent - GREATEST(p_count, 0), 0)
   WHERE tenant_id = p_tenant_id AND day = p_day
  RETURNING sent;
$$;

REVOKE ALL ON TABLE public.tenant_mcp_connections FROM anon, authenticated;
REVOKE ALL ON TABLE public.claude_send_days FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.claude_reserve_sends(uuid, date, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claude_release_sends(uuid, date, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claude_reserve_sends(uuid, date, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claude_release_sends(uuid, date, integer) TO service_role;
