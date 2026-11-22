-- Undo 311_teach_offers_followups.sql. Run in the SQL Editor (the Supabase MCP declines DROP).
ALTER TABLE public.reengagement_logs DROP COLUMN IF EXISTS reason;
DROP TABLE IF EXISTS public.ai_offers;
DROP TABLE IF EXISTS public.ai_teach_items;
