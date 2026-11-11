-- 258_companion_kb_search.sql
-- Anril Agents knowledge base, part 2: one search function over the passages of ONE collection
-- of ONE business, for one tier (1 = main resource, 2 = books).
--
-- match_companion_kb_chunks returns up to p_count rows per list; Python merges the lists by rank
-- (reciprocal rank fusion) and a judge then checks the survivors. The lists ("source" column):
--   vector_en / vector_ta  meaning: cosine similarity to the English / Tamil query (score 1 = same).
--                          Only passages whose embedding_model = p_model are compared: numbers
--                          from two models mean nothing next to each other.
--   words                  full-text match on either query. 'simple' config (Postgres has no Tamil
--                          stemmer). Any word may match (OR), ranked by ts_rank: a chat question
--                          never contains every word of the passage that answers it.
--   trigram                spelling variants: best word_similarity of any key term ("shani" finds
--                          "sani"). Floor 0.3.
--   question               tier 1 only: the query is close to a signpost question written for the
--                          passage. The PASSAGE is returned, never the question text.
--
-- Example: p_tier 1, p_query_en "Does Saturn in the 7th house delay marriage?", p_terms
-- {sani, shani, சனி} -> the main resource's page-12 passage comes back in several lists.
--
-- Like match_memory_chunks (256): plain SQL, STABLE, tenant and collection filter inside the
-- function, exact ranking over the scoped rows (no approximate index), service role only.
-- The trigram list scans the scoped rows directly, so no trigram index is added: it would only
-- cost space. Undo: migrations/undo/258_companion_kb_search_undo.sql

SET LOCAL lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS companion_kb_chunks_tsv_idx ON companion_kb_chunks USING gin (tsv);

CREATE OR REPLACE FUNCTION match_companion_kb_chunks(
  p_tenant uuid, p_collection uuid, p_tier integer, p_model text,
  p_embedding_en vector(768), p_embedding_ta vector(768),
  p_query_en text, p_query_ta text, p_terms text[], p_count integer)
RETURNS TABLE (id uuid, document_id uuid, document_title text, tier smallint, heading_path text,
               text text, page_from integer, page_to integer, source text, score double precision)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  WITH scope AS MATERIALIZED (
    SELECT c.id, c.document_id, d.title AS document_title, c.tier, c.heading_path, c.text,
           c.page_from, c.page_to, c.embedding, c.embedding_model, c.tsv
    FROM companion_kb_chunks c
    JOIN companion_kb_documents d ON d.id = c.document_id AND d.tenant_id = p_tenant
    WHERE c.tenant_id = p_tenant AND c.collection_id = p_collection AND c.tier = p_tier
  ),
  q AS (
    -- "saturn & 7th & house" -> "saturn | 7th | house": any word may match.
    SELECT replace(plainto_tsquery('simple', coalesce(p_query_en, '') || ' ' || coalesce(p_query_ta, ''))::text,
                   '&', '|')::tsquery AS any_word
  ),
  by_vector_en AS (
    SELECT s.id, 'vector_en'::text AS source, (1 - (s.embedding <=> p_embedding_en))::double precision AS score
    FROM scope s
    WHERE p_embedding_en IS NOT NULL AND s.embedding IS NOT NULL AND s.embedding_model = p_model
    ORDER BY s.embedding <=> p_embedding_en
    LIMIT p_count
  ),
  by_vector_ta AS (
    SELECT s.id, 'vector_ta'::text AS source, (1 - (s.embedding <=> p_embedding_ta))::double precision AS score
    FROM scope s
    WHERE p_embedding_ta IS NOT NULL AND s.embedding IS NOT NULL AND s.embedding_model = p_model
    ORDER BY s.embedding <=> p_embedding_ta
    LIMIT p_count
  ),
  by_words AS (
    SELECT s.id, 'words'::text AS source, ts_rank(s.tsv, q.any_word)::double precision AS score
    FROM scope s, q
    WHERE numnode(q.any_word) > 0 AND s.tsv @@ q.any_word
    ORDER BY ts_rank(s.tsv, q.any_word) DESC
    LIMIT p_count
  ),
  by_trigram AS (
    SELECT t.id, 'trigram'::text AS source, t.score
    FROM (
      SELECT s.id, max(word_similarity(term, s.text))::double precision AS score
      FROM scope s, unnest(coalesce(p_terms, '{}'::text[])) AS term
      WHERE length(btrim(term)) >= 3
      GROUP BY s.id
    ) t
    WHERE t.score >= 0.3
    ORDER BY t.score DESC
    LIMIT p_count
  ),
  by_question AS (
    SELECT k.id, 'question'::text AS source, k.score
    FROM (
      SELECT s.id, max(GREATEST(
               CASE WHEN p_embedding_en IS NULL THEN 0 ELSE 1 - (cq.embedding <=> p_embedding_en) END,
               CASE WHEN p_embedding_ta IS NULL THEN 0 ELSE 1 - (cq.embedding <=> p_embedding_ta) END
             ))::double precision AS score
      FROM companion_kb_chunk_questions cq
      JOIN scope s ON s.id = cq.chunk_id
      WHERE p_tier = 1 AND cq.tenant_id = p_tenant AND cq.collection_id = p_collection
        AND cq.embedding IS NOT NULL AND cq.embedding_model = p_model
        AND (p_embedding_en IS NOT NULL OR p_embedding_ta IS NOT NULL)
      GROUP BY s.id
    ) k
    ORDER BY k.score DESC
    LIMIT p_count
  ),
  hits AS (
    SELECT * FROM by_vector_en
    UNION ALL SELECT * FROM by_vector_ta
    UNION ALL SELECT * FROM by_words
    UNION ALL SELECT * FROM by_trigram
    UNION ALL SELECT * FROM by_question
  )
  SELECT s.id, s.document_id, s.document_title, s.tier, s.heading_path, s.text, s.page_from, s.page_to,
         h.source, h.score
  FROM hits h JOIN scope s ON s.id = h.id;
$$;

REVOKE ALL ON FUNCTION match_companion_kb_chunks(uuid, uuid, integer, text, vector, vector, text, text, text[], integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION match_companion_kb_chunks(uuid, uuid, integer, text, vector, vector, text, text, text[], integer)
  TO service_role;
