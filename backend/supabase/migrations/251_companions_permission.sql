-- Anril Agents (companion) routes move from settings.manage to their own key,
-- companions.manage. Grant it to every role that has settings.manage today,
-- so no manager loses access when the backend switches over.
-- Apply BEFORE the backend deploy that ships the new guard.
-- Idempotent: running it twice adds nothing (array(select distinct ...)).
update public.tenant_roles r
set permissions = (
  select array(
    select distinct p from unnest(r.permissions || array['companions.manage']) as p
    order by p
  )
)
where r.permissions @> array['settings.manage']
  and not (r.permissions @> array['companions.manage']);
