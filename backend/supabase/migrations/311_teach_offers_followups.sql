-- 311_teach_offers_followups.sql — v9.2 Batch D (Messages).
--   ai_teach_items   ONE shared list the AI agent is taught from:
--                      kind 'answer' = a customer doubt/question and how to answer it. Saved from
--                        Anril Setup › Teach & offers, from Chats "Teach the AI agent?" (after a reply),
--                        and from Brain "Couldn't answer". Same question (match_key) = one row, so it
--                        is counted once; times_taught counts repeats.
--                      kind 'word'   = a word the shop uses and what it means ("pattu" = silk saree).
--   ai_offers        offers on now. Each has an end date; the AI mentions an offer only while
--                    starts_on <= today (IST) <= ends_on, and stops after. source 'reach' = added when
--                    a Reach campaign was marked as an offer.
--   reengagement_logs.reason   plain-words reason when a follow-up step failed or was skipped,
--                    for Auto-Messages › Sent.
-- RLS on, no policies, on the new tables: backend service key only. Additive.
-- Undo: undo/311_teach_offers_followups_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.ai_teach_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('answer', 'word')),
  prompt        text NOT NULL CHECK (length(btrim(prompt)) BETWEEN 1 AND 300),
  reply         text NOT NULL CHECK (length(btrim(reply)) BETWEEN 1 AND 1000),
  match_key     text NOT NULL,
  source        text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'chat', 'couldnt_answer')),
  times_taught  integer NOT NULL DEFAULT 1,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_teach_items_key_uq ON public.ai_teach_items (tenant_id, kind, match_key);
ALTER TABLE public.ai_teach_items ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.ai_offers (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  title         text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 120),
  details       text CHECK (details IS NULL OR length(details) <= 500),
  starts_on     date NOT NULL DEFAULT ((now() AT TIME ZONE 'Asia/Kolkata')::date),
  ends_on       date NOT NULL,
  source        text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'reach')),
  broadcast_ref text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  CONSTRAINT ai_offers_dates_ck CHECK (ends_on >= starts_on)
);
CREATE INDEX IF NOT EXISTS ai_offers_tenant_end_idx ON public.ai_offers (tenant_id, ends_on) WHERE deleted_at IS NULL;
ALTER TABLE public.ai_offers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.reengagement_logs ADD COLUMN IF NOT EXISTS reason text;
