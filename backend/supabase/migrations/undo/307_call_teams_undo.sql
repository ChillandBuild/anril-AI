-- Undo 307_call_teams.sql. Run in the SQL Editor (the Supabase MCP declines DROP).
UPDATE public.tenant_roles SET permissions = array_remove(permissions, 'leads.download') WHERE 'leads.download' = ANY (permissions);
ALTER TABLE public.call_logs DROP COLUMN IF EXISTS transcript_en, DROP COLUMN IF EXISTS transcript_en_at;
ALTER TABLE public.telecalling_upload_batches DROP COLUMN IF EXISTS undone_at, DROP COLUMN IF EXISTS undone_by, DROP COLUMN IF EXISTS undone_count;
ALTER TABLE public.follow_up_jobs DROP COLUMN IF EXISTS reminder_notified_at, DROP COLUMN IF EXISTS late_alerted_at;
ALTER TABLE public.callers DROP COLUMN IF EXISTS team_id;
DROP TABLE IF EXISTS public.call_team_leaders;
DROP TABLE IF EXISTS public.call_teams;
