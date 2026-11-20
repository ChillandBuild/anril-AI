-- Undo 303_client_claude.sql. Run in the SQL Editor (the Supabase MCP declines DROP).
DROP FUNCTION IF EXISTS public.claude_reserve_sends(uuid, date, integer, integer);
DROP FUNCTION IF EXISTS public.claude_release_sends(uuid, date, integer);
DROP TABLE IF EXISTS public.claude_send_days;
DROP TABLE IF EXISTS public.tenant_mcp_connections;
