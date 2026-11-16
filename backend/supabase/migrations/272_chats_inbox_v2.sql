-- 272_chats_inbox_v2.sql
-- Chats page redesign (2026-11-16): Needs you / AI handling tabs, server-side filters
-- with exact counts, shared unread, booked / not-buying results, who sent each
-- teammate reply, and who made each sale.
--
-- Additive only. get_conversation_leads (223) stays for the backend still deployed;
-- drop it once the backend that calls get_inbox_chats is live.
SET LOCAL lock_timeout = '5s';

-- Who on the team sent an outbound message (null = AI, automation, or older rows).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_by_user_id uuid;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_by_name text;

-- Shared unread: the last time ANY teammate opened the chat.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS team_seen_at timestamptz;
-- Result of the chat, set from the Chats page (Came / Paid comes from won deals).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS booked_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS booked_for timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS booking_note text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lost_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lost_reason text;

-- Who made the sale (a caller on the team), picked in Record payment.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS sold_by uuid REFERENCES callers(id) ON DELETE SET NULL;

-- Start every existing chat as read, so the first deploy doesn't light up 1,600 badges.
UPDATE leads SET team_seen_at = now() WHERE team_seen_at IS NULL;

CREATE INDEX IF NOT EXISTS deals_lead_stage_idx ON deals (lead_id, stage);

-- One row per chat with every flag the inbox filters on. Folder and channel are
-- returned (not applied) so the list and the counts share one definition.
CREATE OR REPLACE FUNCTION public.inbox_chat_rows(
  p_tenant_id uuid,
  p_caller_id uuid,
  p_search text,
  p_ai_master boolean,
  p_segments text[],
  p_results text[],
  p_came_from text[],
  p_handled_by text[],
  p_waiting text[],
  p_since timestamptz,
  p_tag_id uuid
)
RETURNS TABLE(
  lead_id uuid,
  folder text,
  inbox_group smallint,
  channel text,
  pinned_at timestamptz,
  last_reply_at timestamptz,
  last_message_content text,
  waiting_since timestamptz
)
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
  with conversation_leads as (
    select
      m.lead_id,
      max(m.created_at) as last_reply_at,
      (select m2.content from messages m2 where m2.lead_id = m.lead_id and m2.tenant_id = p_tenant_id order by m2.created_at desc limit 1) as last_message_content
    from messages m
    where m.tenant_id = p_tenant_id
      and m.lead_id is not null
      and exists (
        select 1 from messages mx
        where mx.lead_id = m.lead_id
          and mx.tenant_id = p_tenant_id
          and (
            mx.direction = 'inbound'
            or (mx.direction = 'outbound' and mx.content not like '[Template:%]')
          )
      )
    group by m.lead_id
  ),
  pinned_leads as (
    select l.id as lead_id
    from leads l
    where l.tenant_id = p_tenant_id
      and l.pinned_at is not null
      and l.opted_out is not true
      and l.deleted_at is null
  ),
  -- FULL OUTER JOIN, never UNION: one row per lead (see subsystem-notes, Conversations UI).
  combined as (
    select coalesce(cl.lead_id, pl.lead_id) as lead_id, cl.last_reply_at, cl.last_message_content
    from pinned_leads pl
    full outer join conversation_leads cl on cl.lead_id = pl.lead_id
  ),
  flagged as (
    select
      c.lead_id,
      c.last_reply_at,
      c.last_message_content,
      l.pinned_at,
      l.segment,
      l.assigned_to,
      case
        when l.blocked_at is not null then 'blocked'
        when l.archived_at is not null then 'archived'
        else 'chats'
      end as folder,
      case when l.source in ('instagram', 'telegram', 'facebook') then l.source else 'whatsapp' end as channel,
      (coalesce(l.needs_human_attention, false) or coalesce(l.needs_human_intervention, false)) as needs_you,
      (p_ai_master and coalesce(l.ai_enabled, true)) as ai_on,
      case
        when l.converted_at is not null
          or exists (select 1 from deals d where d.lead_id = l.id and d.tenant_id = p_tenant_id and d.stage = 'won')
          then 'paid'
        when l.lost_at is not null then 'lost'
        when l.booked_at is not null then 'booked'
        else 'none'
      end as result,
      case
        when l.ad_campaign_id is not null or l.external_ad_id is not null then 'meta_ads'
        when l.source in ('website', 'indiamart', 'justdial', 'upload', 'manual') then l.source
        else 'direct'
      end as came_from,
      l.last_inbound_at,
      l.team_seen_at
    from combined c
    join leads l on l.id = c.lead_id and l.tenant_id = p_tenant_id
    where l.deleted_at is null
      and (p_caller_id is null or l.assigned_to = p_caller_id or l.needs_human_attention is true)
      and (
        p_search is null or p_search = ''
        or l.name ilike '%' || p_search || '%'
        or l.phone ilike '%' || p_search || '%'
        or l.tg_username ilike '%' || p_search || '%'
      )
      and (p_since is null or c.last_reply_at >= p_since)
      and (p_tag_id is null or exists (
        select 1 from lead_tag_interest t where t.lead_id = l.id and t.tenant_id = p_tenant_id and t.tag_id = p_tag_id
      ))
  )
  select
    f.lead_id,
    f.folder,
    (case when f.needs_you then 0 when f.ai_on then 1 else 2 end)::smallint as inbox_group,
    f.channel,
    f.pinned_at,
    f.last_reply_at,
    f.last_message_content,
    -- The customer is waiting when their message is the latest one.
    case when f.last_inbound_at is not null and f.last_inbound_at >= coalesce(f.last_reply_at, f.last_inbound_at)
      then f.last_inbound_at end as waiting_since
  from flagged f
  where (p_segments is null or cardinality(p_segments) = 0 or f.segment = any(p_segments))
    and (p_results is null or cardinality(p_results) = 0 or f.result = any(p_results))
    and (p_came_from is null or cardinality(p_came_from) = 0 or f.came_from = any(p_came_from))
    and (
      p_handled_by is null or cardinality(p_handled_by) = 0
      or ('ai' = any(p_handled_by) and f.ai_on and not f.needs_you)
      or ('nobody' = any(p_handled_by) and f.assigned_to is null)
      or (f.assigned_to::text = any(p_handled_by))
    )
    and (
      p_waiting is null or cardinality(p_waiting) = 0
      or ('unread' = any(p_waiting) and f.last_inbound_at > coalesce(f.team_seen_at, '-infinity'::timestamptz))
      or ('over_1h' = any(p_waiting) and f.last_inbound_at >= coalesce(f.last_reply_at, f.last_inbound_at)
          and f.last_inbound_at < now() - interval '1 hour')
      or ('payment_pending' = any(p_waiting) and exists (
            select 1 from deals d where d.lead_id = f.lead_id and d.tenant_id = p_tenant_id and d.stage = 'awaiting_payment'))
    );
$function$;

-- A page of chats for one tab. p_view: needs_you (every active chat, needs-you first),
-- ai_handling, archived, blocked.
CREATE OR REPLACE FUNCTION public.get_inbox_chats(
  p_tenant_id uuid,
  p_limit integer,
  p_offset integer,
  p_view text,
  p_caller_id uuid DEFAULT NULL,
  p_search text DEFAULT NULL,
  p_ai_master boolean DEFAULT true,
  p_channels text[] DEFAULT NULL,
  p_segments text[] DEFAULT NULL,
  p_results text[] DEFAULT NULL,
  p_came_from text[] DEFAULT NULL,
  p_handled_by text[] DEFAULT NULL,
  p_waiting text[] DEFAULT NULL,
  p_since timestamptz DEFAULT NULL,
  p_tag_id uuid DEFAULT NULL
)
RETURNS TABLE(
  lead_id uuid,
  inbox_group smallint,
  last_reply_at timestamptz,
  last_message_content text,
  waiting_since timestamptz,
  unread_count integer,
  total bigint
)
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
  with v as (
    select r.*
    from inbox_chat_rows(p_tenant_id, p_caller_id, p_search, p_ai_master, p_segments, p_results,
                         p_came_from, p_handled_by, p_waiting, p_since, p_tag_id) r
    where (p_channels is null or cardinality(p_channels) = 0 or r.channel = any(p_channels))
      and case p_view
            when 'archived' then r.folder = 'archived'
            when 'blocked' then r.folder = 'blocked'
            when 'ai_handling' then r.folder = 'chats' and r.inbox_group = 1
            else r.folder = 'chats'
          end
  ),
  page as (
    select v.*, count(*) over () as total
    from v
    order by
      case when p_view = 'needs_you' then v.inbox_group else 0 end,
      -- Needs you: longest-waiting first.
      case when p_view = 'needs_you' and v.inbox_group = 0 then coalesce(v.waiting_since, v.last_reply_at) end asc nulls last,
      v.pinned_at desc nulls last,
      v.last_reply_at desc nulls last,
      v.lead_id
    limit p_limit
    offset p_offset
  )
  select
    p.lead_id,
    p.inbox_group,
    p.last_reply_at,
    p.last_message_content,
    p.waiting_since,
    (
      select count(*)::integer from (
        select 1 from messages m
        join leads l on l.id = p.lead_id
        where m.lead_id = p.lead_id and m.tenant_id = p_tenant_id and m.direction = 'inbound'
          and m.created_at > coalesce(l.team_seen_at, '-infinity'::timestamptz)
        limit 99
      ) u
    ) as unread_count,
    p.total
  from page p
  order by
    case when p_view = 'needs_you' then p.inbox_group else 0 end,
    case when p_view = 'needs_you' and p.inbox_group = 0 then coalesce(p.waiting_since, p.last_reply_at) end asc nulls last,
    p.pinned_at desc nulls last,
    p.last_reply_at desc nulls last,
    p.lead_id;
$function$;

-- Tab and channel counts under the same filters. Channel counts ignore the channel
-- filter (so every chip shows its own number) and follow p_view.
CREATE OR REPLACE FUNCTION public.get_inbox_counts(
  p_tenant_id uuid,
  p_view text,
  p_caller_id uuid DEFAULT NULL,
  p_search text DEFAULT NULL,
  p_ai_master boolean DEFAULT true,
  p_channels text[] DEFAULT NULL,
  p_segments text[] DEFAULT NULL,
  p_results text[] DEFAULT NULL,
  p_came_from text[] DEFAULT NULL,
  p_handled_by text[] DEFAULT NULL,
  p_waiting text[] DEFAULT NULL,
  p_since timestamptz DEFAULT NULL,
  p_tag_id uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
  with r as (
    select * from inbox_chat_rows(p_tenant_id, p_caller_id, p_search, p_ai_master, p_segments, p_results,
                                  p_came_from, p_handled_by, p_waiting, p_since, p_tag_id)
  ),
  ch as (
    select * from r where p_channels is null or cardinality(p_channels) = 0 or r.channel = any(p_channels)
  ),
  in_view as (
    select * from r
    where case p_view
            when 'archived' then r.folder = 'archived'
            when 'blocked' then r.folder = 'blocked'
            when 'ai_handling' then r.folder = 'chats' and r.inbox_group = 1
            else r.folder = 'chats'
          end
  )
  select jsonb_build_object(
    'needs_you', (select count(*) from ch where folder = 'chats' and inbox_group = 0),
    'ai_handling', (select count(*) from ch where folder = 'chats' and inbox_group = 1),
    'all_active', (select count(*) from ch where folder = 'chats'),
    'channels', jsonb_build_object(
      'all', (select count(*) from in_view),
      'whatsapp', (select count(*) from in_view where channel = 'whatsapp'),
      'instagram', (select count(*) from in_view where channel = 'instagram'),
      'facebook', (select count(*) from in_view where channel = 'facebook'),
      'telegram', (select count(*) from in_view where channel = 'telegram')
    )
  );
$function$;

REVOKE ALL ON FUNCTION public.inbox_chat_rows(uuid, uuid, text, boolean, text[], text[], text[], text[], text[], timestamptz, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_inbox_chats(uuid, integer, integer, text, uuid, text, boolean, text[], text[], text[], text[], text[], text[], timestamptz, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_inbox_counts(uuid, text, uuid, text, boolean, text[], text[], text[], text[], text[], text[], timestamptz, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.inbox_chat_rows(uuid, uuid, text, boolean, text[], text[], text[], text[], text[], timestamptz, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_inbox_chats(uuid, integer, integer, text, uuid, text, boolean, text[], text[], text[], text[], text[], text[], timestamptz, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_inbox_counts(uuid, text, uuid, text, boolean, text[], text[], text[], text[], text[], text[], timestamptz, uuid) TO service_role;
