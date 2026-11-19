-- 295_mcp_connections.sql
-- Claude Access (read-only admin MCP, docs/specs/anril-admin-mcp.md). One row per (system admin,
-- OAuth client). A row is created when the admin clicks Allow on the consent screen; only a row
-- with status 'active' lets the MCP answer, so flipping it to 'revoked' is the off switch.
-- RLS on with no policies: only the backend's service key can read or write it.
-- Additive. Apply BEFORE MCP_ENABLED is switched on.
-- Undo: undo/295_mcp_connections_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.mcp_connections (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL,
  client_id    text NOT NULL,
  label        text,
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at   timestamptz,
  UNIQUE (user_id, client_id)
);

ALTER TABLE public.mcp_connections ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.mcp_connections IS
  'Claude Access connections for the read-only admin MCP. status=active is the on switch. Service key only.';
