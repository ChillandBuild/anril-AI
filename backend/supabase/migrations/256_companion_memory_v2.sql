-- 256_companion_memory_v2.sql
-- Aira Companion Level 2 memory, card engine v2: the person's own day, safe parallel runs,
-- one-trip day context, and long-term search over old messages, diary lines and closed facts.
--
-- - companion_end_users.timezone: the person's IANA zone ("America/Toronto"), sent by the client app
--   with each chat message. NULL = use the character's.
-- - companions.timezone: the owner's setting, default 'Asia/Kolkata'. "Today" for the recap and the
--   diary day is the person's local day.
-- - companion_memory_state:
--     diary_through    last local day whose diary is closed (written or skipped) for this pair
--     day_retry_after  a failed same-day refresh waits until this time (30 min) before trying again
--     busy_until       a run holds the pair until this time (claim_memory_pair); others skip it
--     search_backfilled_at  the one-time backfill indexed this pair's old history for search
--     forget_pending   {"items": [...], "tries": n}: a "forget that" cleanup that failed; the hourly job
--                      retries it and clears it (forget-me deletes the row with everything else)
-- - companion_memory_chunks: searchable pieces per (character, person):
--     kind 'messages' = a window of 8 chat messages (both sides, 2 overlap), source_key = first message id
--     kind 'diary'    = one diary line, source_key = the day
--     kind 'fact'     = a closed card fact ("Lived in Chennai, until Mar 2026"), source_key = fact id
--   embedding vector(768) may be NULL (embedding failed); the trigram half still finds the row.
--   No HNSW index on purpose: every search is for ONE person (a few hundred to a few thousand rows),
--   so match_memory_chunks filters by person first and ranks exactly. An approximate index filtered
--   after the scan would silently drop matches.
--
-- RLS on with no policies: service role only, like 248/255. Functions are service-role only.

SET LOCAL lock_timeout = '5s';

ALTER TABLE companion_end_users
  ADD COLUMN IF NOT EXISTS timezone text CHECK (timezone IS NULL OR char_length(timezone) BETWEEN 1 AND 64);

ALTER TABLE companions
  ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata'
    CHECK (char_length(timezone) BETWEEN 1 AND 64);

ALTER TABLE companion_memory_state
  ADD COLUMN IF NOT EXISTS diary_through date,
  ADD COLUMN IF NOT EXISTS day_retry_after timestamptz,
  ADD COLUMN IF NOT EXISTS busy_until timestamptz,
  ADD COLUMN IF NOT EXISTS search_backfilled_at timestamptz,
  ADD COLUMN IF NOT EXISTS forget_pending jsonb;

-- Diary lines can now be longer (Tamil uses more characters per idea): 300 → 600.
ALTER TABLE companion_memory_diary DROP CONSTRAINT IF EXISTS companion_memory_diary_text_check;
ALTER TABLE companion_memory_diary
  ADD CONSTRAINT companion_memory_diary_text_check CHECK (length(btrim(text)) BETWEEN 1 AND 600);


-- One run per pair at a time, across every server process. True = this caller holds the pair
-- for p_seconds. Creates the state row when the pair has none yet.
CREATE OR REPLACE FUNCTION claim_memory_pair(p_tenant uuid, p_companion uuid, p_end_user uuid,
                                             p_seconds integer)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  claimed integer;
BEGIN
  INSERT INTO companion_memory_state AS s (tenant_id, companion_id, end_user_id, busy_until, updated_at)
  VALUES (p_tenant, p_companion, p_end_user, now() + make_interval(secs => p_seconds), now())
  ON CONFLICT (companion_id, end_user_id) DO UPDATE
    SET busy_until = EXCLUDED.busy_until
    WHERE s.tenant_id = p_tenant AND (s.busy_until IS NULL OR s.busy_until < now());
  GET DIAGNOSTICS claimed = ROW_COUNT;
  RETURN claimed = 1;
END;
$$;


-- The reply path's recap + recent diary lines in one round trip.
-- {"recap": text|null, "recap_day": "YYYY-MM-DD"|null, "diary": [{"day","text"}, ...newest first]}
CREATE OR REPLACE FUNCTION companion_day_context(p_tenant uuid, p_companion uuid, p_end_user uuid,
                                                 p_before_day date, p_days integer)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  SELECT jsonb_build_object(
    'recap', (SELECT today_recap FROM companion_memory_state
              WHERE tenant_id = p_tenant AND companion_id = p_companion AND end_user_id = p_end_user),
    'recap_day', (SELECT recap_day FROM companion_memory_state
                  WHERE tenant_id = p_tenant AND companion_id = p_companion AND end_user_id = p_end_user),
    'diary', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('day', d.day, 'text', d.text) ORDER BY d.day DESC)
      FROM (SELECT day, text FROM companion_memory_diary
            WHERE tenant_id = p_tenant AND companion_id = p_companion AND end_user_id = p_end_user
              AND day < p_before_day
            ORDER BY day DESC LIMIT p_days) d), '[]'::jsonb));
$$;


CREATE TABLE IF NOT EXISTS companion_memory_chunks (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id  uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('messages', 'diary', 'fact')),
  source_key   text NOT NULL CHECK (char_length(source_key) BETWEEN 1 AND 64),
  day          date NOT NULL,
  text         text NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 4000),
  embedding    vector(768),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (companion_id, end_user_id, kind, source_key)
);
CREATE INDEX IF NOT EXISTS companion_memory_chunks_person_idx
  ON companion_memory_chunks (tenant_id, end_user_id, companion_id);

ALTER TABLE companion_memory_chunks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON companion_memory_chunks FROM anon, authenticated;


-- Hybrid search for ONE person: the top p_count rows by cosine similarity and the top p_count by
-- trigram word similarity, among the characters in p_companions (the memory scope). Python fuses
-- the two lists (RRF) and applies the similarity floor. 'vector' rows carry score = cosine
-- similarity (1 = same); 'trigram' rows carry score = word_similarity (0..1).
CREATE OR REPLACE FUNCTION match_memory_chunks(p_tenant uuid, p_companions uuid[], p_end_user uuid,
                                               p_embedding vector(768), p_query text, p_count integer)
RETURNS TABLE (id uuid, companion_id uuid, kind text, day date, text text, source text, score double precision)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  WITH mine AS MATERIALIZED (
    SELECT c.id, c.companion_id, c.kind, c.day, c.text, c.embedding
    FROM companion_memory_chunks c
    WHERE c.tenant_id = p_tenant AND c.end_user_id = p_end_user AND c.companion_id = ANY (p_companions)
  ),
  by_vector AS (
    SELECT m.id, m.companion_id, m.kind, m.day, m.text, 'vector'::text AS source,
           (1 - (m.embedding <=> p_embedding))::double precision AS score
    FROM mine m
    WHERE p_embedding IS NOT NULL AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> p_embedding
    LIMIT p_count
  ),
  by_trigram AS (
    SELECT m.id, m.companion_id, m.kind, m.day, m.text, 'trigram'::text AS source,
           word_similarity(p_query, m.text)::double precision AS score
    FROM mine m
    WHERE coalesce(p_query, '') <> ''
    ORDER BY word_similarity(p_query, m.text) DESC
    LIMIT p_count
  )
  SELECT * FROM by_vector
  UNION ALL
  SELECT * FROM by_trigram WHERE score > 0;
$$;

REVOKE ALL ON FUNCTION claim_memory_pair(uuid, uuid, uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION companion_day_context(uuid, uuid, uuid, date, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION match_memory_chunks(uuid, uuid[], uuid, vector, text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_memory_pair(uuid, uuid, uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION companion_day_context(uuid, uuid, uuid, date, integer) TO service_role;
GRANT EXECUTE ON FUNCTION match_memory_chunks(uuid, uuid[], uuid, vector, text, integer) TO service_role;
