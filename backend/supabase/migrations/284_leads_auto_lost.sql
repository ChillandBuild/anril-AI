-- 284_leads_auto_lost.sql
-- Engage > Inbound leads: "Lost · stopped replying" set by Anril itself, with Undo.
--
-- - leads.lost_auto: true when Anril (not a person) marked the lead Lost. Cleared by any
--   manual Not buying, by Undo, and by a booking.
-- - leads.auto_lost_dismissed_at: when someone pressed Undo on an automatic Lost. The job
--   never marks that lead again for a follow-up sent before this moment.
-- - stopped_replying_leads(p_cutoff, p_limit): leads to mark. All must hold:
--     * inbound lead, not deleted, not on Said stop, no result yet (not booked, lost, paid);
--     * their newest follow-up (reengagement_logs sent / sent_fallback) went out before p_cutoff
--       (the job passes now - 3 days);
--     * that follow-up was the business's last one of its kind: its step has the longest
--       delay among the business's steps of the same type, so no further follow-up is coming;
--     * nothing came in from them after it, and nobody pressed Undo after it.
--   Service role only (the job), like the other sweeps.

SET LOCAL lock_timeout = '5s';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS lost_auto boolean NOT NULL DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS auto_lost_dismissed_at timestamptz;

CREATE OR REPLACE FUNCTION public.stopped_replying_leads(p_cutoff timestamptz, p_limit integer DEFAULT 500)
RETURNS TABLE(lead_id uuid, tenant_id uuid, last_follow_up_at timestamptz)
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
  with latest as (
    select distinct on (rl.lead_id) rl.lead_id, rl.tenant_id, rl.step_id, rl.sent_at
    from reengagement_logs rl
    where rl.status in ('sent', 'sent_fallback')
    order by rl.lead_id, rl.sent_at desc
  )
  select l.id, l.tenant_id, lt.sent_at
  from latest lt
  join leads l on l.id = lt.lead_id and l.tenant_id = lt.tenant_id
  join reengagement_steps s on s.id = lt.step_id
  where lt.sent_at < p_cutoff
    and l.deleted_at is null
    and l.source in ('whatsapp', 'instagram', 'facebook', 'telegram', 'indiamart', 'justdial', 'meta_form')
    and l.opted_out is not true
    and l.lost_at is null and l.booked_at is null and l.converted_at is null
    and not exists (select 1 from deals d where d.lead_id = l.id and d.stage = 'won')
    and (l.auto_lost_dismissed_at is null or l.auto_lost_dismissed_at < lt.sent_at)
    and not exists (
      select 1 from messages m
      where m.lead_id = l.id and m.direction = 'inbound' and m.created_at > lt.sent_at
    )
    and s.delay_hours >= (
      select max(s2.delay_hours) from reengagement_steps s2
      where s2.tenant_id = s.tenant_id and s2.type = s.type
    )
  limit p_limit
$function$;

REVOKE EXECUTE ON FUNCTION public.stopped_replying_leads(timestamptz, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.stopped_replying_leads(timestamptz, integer) TO service_role;
