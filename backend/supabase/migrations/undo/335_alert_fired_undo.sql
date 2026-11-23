-- Undo 335_alert_fired.sql. Drops the once-a-day ledger (the two alerts then send nothing until it is back).
SET LOCAL lock_timeout = '5s';

DROP TABLE IF EXISTS public.alert_fired;
