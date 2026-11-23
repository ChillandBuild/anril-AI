-- Undo 323_alerts_automations.sql. Drops the pause log and the come-back send log (the 30-day rule starts again).
SET LOCAL lock_timeout = '5s';

DROP TABLE IF EXISTS public.comeback_offer_sends;
DROP TABLE IF EXISTS public.automation_pauses;
