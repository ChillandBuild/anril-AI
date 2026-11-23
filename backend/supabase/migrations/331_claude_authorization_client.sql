-- Which OAuth app is this consent request for? (Anril Admin or Anril AI)
--
-- Supabase has ONE consent page for the whole project, and it stamps a request with whichever login
-- opens it first. The consent page therefore has to know which connector is asking BEFORE it opens
-- the request, so it can use the right login (the operator's or the client owner's). Read-only,
-- backend (service role) only; it returns the app id and nothing else.
create or replace function public.claude_authorization_client(p_authorization_id text)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select client_id
  from auth.oauth_authorizations
  where authorization_id = p_authorization_id
    and status = 'pending'
    and expires_at > now()
  limit 1
$$;

revoke all on function public.claude_authorization_client(text) from public, anon, authenticated;
grant execute on function public.claude_authorization_client(text) to service_role;
