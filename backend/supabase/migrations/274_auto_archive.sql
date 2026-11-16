-- 274_auto_archive.sql
-- Chats > Archived (2026-11-17):
--  1. An archived chat comes back to the Inbox by itself when the customer writes again
--     (trigger on inbound messages, every channel). Blocked chats stay blocked.
--  2. A daily job (queue task auto-archive-idle, 04:00 IST) archives chats with no message
--     either way for 30 days. Never one that needs a person, is pinned, or is blocked.
-- leads.archived_reason marks how a chat was archived: null = by a teammate,
-- 'idle_30d' = by the daily job (so the page can say "by itself", and it can be undone in bulk).
SET LOCAL lock_timeout = '5s';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS archived_reason text;

CREATE OR REPLACE FUNCTION public.unarchive_on_inbound()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
  IF NEW.direction = 'inbound' AND NEW.lead_id IS NOT NULL THEN
    UPDATE leads
       SET archived_at = NULL, archived_by_name = NULL, archived_reason = NULL
     WHERE id = NEW.lead_id
       AND archived_at IS NOT NULL;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS messages_unarchive_on_inbound ON messages;
CREATE TRIGGER messages_unarchive_on_inbound
  AFTER INSERT ON messages
  FOR EACH ROW
  WHEN (NEW.direction = 'inbound')
  EXECUTE FUNCTION public.unarchive_on_inbound();

-- Archives every tenant's idle chats; returns how many it archived.
CREATE OR REPLACE FUNCTION public.auto_archive_idle_chats(p_days integer DEFAULT 30)
RETURNS integer
LANGUAGE sql
SET search_path TO 'public', 'pg_temp'
AS $function$
  with idle as (
    select l.id
    from leads l
    cross join lateral (
      select max(m.created_at) as last_at from messages m where m.lead_id = l.id and m.tenant_id = l.tenant_id
    ) lm
    where l.deleted_at is null
      and l.archived_at is null
      and l.blocked_at is null
      and l.pinned_at is null
      and coalesce(l.needs_human_attention, false) = false
      and coalesce(l.needs_human_intervention, false) = false
      and lm.last_at is not null
      and lm.last_at < now() - make_interval(days => greatest(p_days, 1))
  ),
  done as (
    update leads l
       set archived_at = now(), archived_by_name = null, archived_reason = 'idle_30d'
      from idle
     where l.id = idle.id
    returning 1
  )
  select count(*)::integer from done;
$function$;

REVOKE ALL ON FUNCTION public.auto_archive_idle_chats(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.auto_archive_idle_chats(integer) TO service_role;
REVOKE ALL ON FUNCTION public.unarchive_on_inbound() FROM PUBLIC, anon, authenticated;
