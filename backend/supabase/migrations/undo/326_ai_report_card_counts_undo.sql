-- Undo 326: the report card goes back to counting on the server (the code falls back by itself).
DROP FUNCTION IF EXISTS public.ai_report_card_counts(uuid, timestamptz, timestamptz);
