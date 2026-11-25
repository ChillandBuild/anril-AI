-- 349_companion_reply_quality.sql
-- Anril Agents quality loop: what went into each live reply, and whether the person liked it.
--
-- 1. companion_reply_trace: one row per saved live reply. What went INTO it, never what was said.
--    Example: Karthik asks Jothidar AI about his job →
--      (Astrotamil, Jothidar AI, <message id>, basis 'own', llm 1900 ms, total 2400 ms,
--       detail {"card_lines": 14, "hits": 0, "dropped_recent_days": 5, "passages": 3})
--    detail holds only whole numbers, true/false and a few fixed words (the list lives in
--    app/companion/trace.py, which drops anything else before the insert).
-- 2. companion_reply_feedback: one row per rated reply. Karthik taps thumbs-down → (<message id>, -1).
--    Tapping again changes that same row; clearing the rating deletes it. No comment text.
--
-- No message text in either table, same promise as companion_request_log (252).
-- Both rows hang off the message: deleting a message (an owner delete, "forget this person", a deleted
-- character) deletes its trace and its rating with it (ON DELETE CASCADE).
--
-- Add-only: two new tables, two indexes. No existing table or row is touched.
-- RLS on with no policies: service role only, like 248, 250 and 252.
-- Must be applied BEFORE the backend that writes these tables is deployed. (The trace write is
-- best-effort and only logs a warning without the table; the feedback call would answer 503.)

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_reply_trace (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id  uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  message_id    uuid NOT NULL UNIQUE REFERENCES companion_messages(id) ON DELETE CASCADE,
  basis         text CHECK (basis IS NULL OR length(basis) <= 20),
  model         text CHECK (model IS NULL OR length(model) <= 80),
  llm_ms        integer NOT NULL CHECK (llm_ms >= 0),
  total_ms      integer NOT NULL CHECK (total_ms >= 0),
  detail        jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (pg_column_size(detail) <= 2000),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS companion_reply_trace_companion_created
  ON companion_reply_trace (tenant_id, companion_id, created_at DESC);

ALTER TABLE companion_reply_trace ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS companion_reply_feedback (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id  uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  message_id    uuid NOT NULL UNIQUE REFERENCES companion_messages(id) ON DELETE CASCADE,
  end_user_id   uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  rating        smallint NOT NULL CHECK (rating IN (-1, 1)),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS companion_reply_feedback_companion_updated
  ON companion_reply_feedback (tenant_id, companion_id, updated_at DESC);

ALTER TABLE companion_reply_feedback ENABLE ROW LEVEL SECURITY;
