-- 318_companion_chart_guard.sql
-- Chart guard for astrology characters whose app sends the finished chart (AstroTamil): birth date, time and
-- place are cut before the reply model sees anything (app data, memory, chat), the prompt gets the chart rules,
-- and every reply's planet/rasi/house claims are checked against the app's chart (one redo, then the
-- astrologer line). Default false = every other character exactly as before.
-- Additive. Safe before or after the code deploy (the code reads it with .get()).
-- Undo: undo/318_companion_chart_guard_undo.sql
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.companions ADD COLUMN IF NOT EXISTS chart_guard boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.companions.chart_guard IS
  'Astrology: hide birth details from the model and check every reply against the chart the app sent.';
