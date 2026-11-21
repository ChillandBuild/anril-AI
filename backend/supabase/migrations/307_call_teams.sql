-- 307_call_teams.sql — v9.2 Batch C (Team): Call IQ teams + leaders, call-back reminder flags,
-- undo an upload, English transcript cache, and the "Download lists" permission.
--   call_teams          one row per team (Team A, Team B) per client.
--   call_team_leaders   who leads which team (a team can have several leaders). user_id = auth user.
--   callers.team_id     the team a telecaller is in (NULL = no team: only owner / see-everyone roles).
--   follow_up_jobs.reminder_notified_at / late_alerted_at   guards so the 10-min-before reminder
--                       and the 15-min-late alert to the team leader fire once.
--   telecalling_upload_batches.undone_*   an upload the owner undid (who, when, how many removed).
--   call_logs.transcript_en / transcript_en_at   English translation, made on demand and kept.
--   leads.download      new permission. Today ANY member can download the inbound leads list; from
--                       now only the owner and roles with leads.download. Every existing custom role
--                       (not Telecaller) gets it here so nobody who downloads today loses it.
-- RLS on, no policies, on the new tables: backend service key only. Additive.
-- Undo: undo/307_call_teams_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.call_teams (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  name       text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 60),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS call_teams_tenant_name_uq ON public.call_teams (tenant_id, lower(btrim(name)));
ALTER TABLE public.call_teams ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.call_team_leaders (
  team_id    uuid NOT NULL REFERENCES public.call_teams(id) ON DELETE CASCADE,
  tenant_id  uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS call_team_leaders_user_idx ON public.call_team_leaders (tenant_id, user_id);
ALTER TABLE public.call_team_leaders ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.callers
  ADD COLUMN IF NOT EXISTS team_id uuid REFERENCES public.call_teams(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS callers_team_idx ON public.callers (tenant_id, team_id);

ALTER TABLE public.follow_up_jobs
  ADD COLUMN IF NOT EXISTS reminder_notified_at timestamptz,
  ADD COLUMN IF NOT EXISTS late_alerted_at timestamptz;

ALTER TABLE public.telecalling_upload_batches
  ADD COLUMN IF NOT EXISTS undone_at timestamptz,
  ADD COLUMN IF NOT EXISTS undone_by uuid,
  ADD COLUMN IF NOT EXISTS undone_count integer;

ALTER TABLE public.call_logs
  ADD COLUMN IF NOT EXISTS transcript_en text,
  ADD COLUMN IF NOT EXISTS transcript_en_at timestamptz;

UPDATE public.tenant_roles
   SET permissions = array_append(permissions, 'leads.download'), updated_at = now()
 WHERE (slug IS NULL OR slug NOT IN ('telecaller', 'team_leader'))
   AND NOT ('leads.download' = ANY (coalesce(permissions, '{}'::text[])));
