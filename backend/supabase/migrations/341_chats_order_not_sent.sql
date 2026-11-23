-- 341_chats_order_not_sent.sql
-- Written and applied live as 332_chats_order_not_sent (23 Nov 2026); renumbered to 341 because Prem's
-- 332_setup_help_stale_handover_error_reports took 332 the same day. Same SQL; nothing to re-run.
-- Chats > Filter > Waiting: "Order not sent" (v9.2 Chats). A chat whose customer has a paid order
-- (stage 'won') that is not yet shipped or delivered and was not taken at the counter.
-- Only inbox_chat_rows changes, and only by one new p_waiting branch; same arguments, so
-- get_inbox_chats / get_inbox_counts pick it up unchanged. Undo: undo/341_chats_order_not_sent_undo.sql
SET LOCAL lock_timeout = '5s';

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
      or ('order_not_sent' = any(p_waiting) and exists (
            select 1 from deals d where d.lead_id = f.lead_id and d.tenant_id = p_tenant_id and d.stage = 'won'
              and coalesce(d.delivery_status, '') not in ('shipped', 'delivered')
              and d.handover is distinct from 'taken'))
    );
$function$;

REVOKE ALL ON FUNCTION public.inbox_chat_rows(uuid, uuid, text, boolean, text[], text[], text[], text[], text[], timestamptz, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.inbox_chat_rows(uuid, uuid, text, boolean, text[], text[], text[], text[], text[], timestamptz, uuid) TO service_role;
