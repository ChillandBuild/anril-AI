-- 335_alert_fired.sql  (v9.2 #29 Alerts: "running low" and "hot customer waiting")
-- One new table, additive only. RLS on, no policies: the backend uses the service key.
--   alert_fired   one row per alert that may ring once per thing per day (stock_low per item, hot_lead_waiting per lead).
--                 The row is claimed (insert, ignore duplicates) BEFORE the bell is sent, so two workers or a re-run of the
--                 sweep can never ring the same thing twice. day is the IST calendar day. Old rows are harmless (a few bytes).
-- Until this runs the two alerts send nothing (the code treats "cannot record" as "do not send").
-- Undo: undo/335_alert_fired_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.alert_fired (
  tenant_id  uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  alert_key  text NOT NULL CHECK (length(alert_key) BETWEEN 1 AND 60),
  subject    text NOT NULL CHECK (length(subject) BETWEEN 1 AND 80),
  day        date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, alert_key, subject, day)
);
CREATE INDEX IF NOT EXISTS idx_alert_fired_day ON public.alert_fired (day);

ALTER TABLE public.alert_fired ENABLE ROW LEVEL SECURITY;
