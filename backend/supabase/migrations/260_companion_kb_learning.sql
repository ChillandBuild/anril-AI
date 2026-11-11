-- 260_companion_kb_learning.sql
-- Anril Agents knowledge base, part 4: learning from real questions.
--
-- - companion_kb_question_log: one row per message that needed the books. Holds ONLY a
--   de-personalised English topic ("Will a separated spouse return?"), never the message as typed,
--   never the answer. There is NO person column in this table, on purpose. Rows older than 90 days
--   are deleted by the nightly job.
--     best: the passages that answered, e.g.
--       [{"document_id": "…", "page_from": 88, "page_to": 88, "score": 3}]   (empty for basis own)
-- - companion_kb_shortcuts: a learned shortcut "this topic is answered on these pages of this
--   book". It remembers the book and page ranges (up to 3), not passage ids: pressing Retry on a
--   page re-cuts the book's passages and gives them new ids. Deleted with its book (CASCADE).
--   status removed_by_owner is kept so the same topic is never learned again.
-- - companion_kb_gaps: a topic asked often that no document answers, shown to the owner.
--
-- Same safety pattern as 257: RLS on with no policies, REVOKE from anon and authenticated,
-- service role only; app/companion/kb/store.py filters every query on tenant_id.
-- Add-only. Undo: migrations/undo/260_companion_kb_learning_undo.sql

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_kb_question_log (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  topic           text NOT NULL CHECK (length(btrim(topic)) BETWEEN 1 AND 500),
  embedding       vector(768),
  embedding_model text,
  basis           text NOT NULL CHECK (basis IN ('primary', 'book', 'own')),
  best            jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_question_log_recent_idx
  ON companion_kb_question_log (tenant_id, companion_id, created_at DESC);
CREATE INDEX IF NOT EXISTS companion_kb_question_log_age_idx
  ON companion_kb_question_log (created_at);

CREATE TABLE IF NOT EXISTS companion_kb_shortcuts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  topic           text NOT NULL CHECK (length(btrim(topic)) BETWEEN 1 AND 500),
  embedding       vector(768),
  embedding_model text,
  document_id     uuid NOT NULL REFERENCES companion_kb_documents(id) ON DELETE CASCADE,
  pages           jsonb NOT NULL DEFAULT '[]'::jsonb
                  CHECK (jsonb_typeof(pages) = 'array' AND jsonb_array_length(pages) BETWEEN 1 AND 3),
  uses            integer NOT NULL DEFAULT 0,
  misses_in_row   smallint NOT NULL DEFAULT 0,
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired', 'removed_by_owner')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_shortcuts_scope_idx
  ON companion_kb_shortcuts (tenant_id, companion_id, status);

CREATE TABLE IF NOT EXISTS companion_kb_gaps (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  topic           text NOT NULL CHECK (length(btrim(topic)) BETWEEN 1 AND 500),
  embedding       vector(768),
  embedding_model text,
  ask_count       integer NOT NULL DEFAULT 0,
  last_asked_at   timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'dismissed', 'covered')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_gaps_scope_idx
  ON companion_kb_gaps (tenant_id, companion_id, status);

ALTER TABLE companion_kb_question_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_shortcuts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_gaps         ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON companion_kb_question_log FROM anon, authenticated;
REVOKE ALL ON companion_kb_shortcuts    FROM anon, authenticated;
REVOKE ALL ON companion_kb_gaps         FROM anon, authenticated;

-- The nightly job's to-do list: which businesses have log rows. Returns ids only, so the job does
-- not read every log row to find them. Example: 3 businesses asked questions -> 3 rows.
CREATE OR REPLACE FUNCTION companion_kb_question_tenants()
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  SELECT DISTINCT q.tenant_id FROM companion_kb_question_log q;
$$;

REVOKE ALL ON FUNCTION companion_kb_question_tenants() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION companion_kb_question_tenants() TO service_role;
