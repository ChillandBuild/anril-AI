-- Undo 343_block_reason.sql
ALTER TABLE public.leads DROP COLUMN IF EXISTS blocked_reason;
