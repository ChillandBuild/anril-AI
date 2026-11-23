-- Undo 332_setup_help_stale_handover_error_reports.sql
DROP TABLE IF EXISTS public.client_error_reports;
DROP INDEX IF EXISTS public.idx_chat_handovers_stale_sweep;
ALTER TABLE public.chat_handovers DROP COLUMN IF EXISTS stale_alerted_at;
DROP TABLE IF EXISTS public.setup_help_requests;
