-- Undo 322_ai_setup_feedback.sql. Run in the SQL Editor (the Supabase MCP declines DROP).
ALTER TABLE public.chat_handovers DROP COLUMN IF EXISTS answered_at;
DROP TABLE IF EXISTS public.ai_reply_feedback;
