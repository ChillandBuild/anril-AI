-- 257_companion_kb_library.sql
-- Anril Agents knowledge base, part 1: the shelves. A separate base from Anril Sales knowledge
-- (knowledge_documents / knowledge_chunks are not touched).
--
-- - companion_kb_collections: a named group of books ("Astrology books"). A character reads one.
-- - companion_kb_documents: one uploaded file. tier 1 = main resource, 2 = book.
--     status: processing -> ready | ready_with_gaps (some pages failed) | failed (no page read).
--     text_layer_trusted: NULL until the 3-page spot-check ran; false = every page goes to OCR.
--     crashed_passes: reading passes in a row that started and did not end cleanly (an
--     unexpected error, or the server died in the middle). At 3 the book is marked failed
--     instead of being retried every minute forever. A clean pass or the owner's Retry sets it
--     back to 0.
--     source 'sales_copy' + source_document_id: copied from an Anril Sales document (no FK on
--     purpose: deleting the Sales document must not touch the copy).
-- - companion_kb_pages: the page ledger. One row per page: pending -> ok | failed. Nothing is
--   dropped silently; a failed page keeps its error.
-- - companion_kb_chunks: one passage. embedding may be NULL (embedding failed): the words half of
--   the search still finds it. embedding_model names the model that made the numbers; search only
--   compares rows of the same model. signposts_at: signpost questions are written (tier 1 only).
--   collection_id and tier are copied from the document so search filters without a join.
-- - companion_kb_chunk_questions: signpost questions for a tier 1 passage. Search aid only; their
--   text never enters a reply.
-- - companions.knowledge_collection_id: the collection a character reads. The ONE change to an
--   existing table. knowledge_tag_id stays but is no longer read.
-- - For each tag a character points at today, an empty collection with the tag's name is made and
--   the character is pointed at it.
-- - Private storage bucket companion-kb-documents: <tenant_id>/<document_id>/original.<ext>.
--
-- No vector index on purpose (same choice as 256): one business has a few thousand passages, the
-- search is exact, no passage is missed.
-- RLS on with no policies: service role only, like 248-256. Isolation is in code:
-- app/companion/kb/store.py is the only module that touches these tables, and every query
-- filters on tenant_id.
-- Add-only. Undo: migrations/undo/257_companion_kb_library_undo.sql

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companion_kb_collections (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name       text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS companion_kb_documents (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- RESTRICT: a collection with books cannot be deleted (the owner deletes the books first).
  collection_id      uuid NOT NULL REFERENCES companion_kb_collections(id) ON DELETE RESTRICT,
  title              text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
  file_type          text NOT NULL CHECK (length(file_type) BETWEEN 1 AND 10),
  size_bytes         bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  storage_path       text CHECK (storage_path IS NULL OR length(storage_path) <= 300),
  tier               smallint NOT NULL DEFAULT 2 CHECK (tier IN (1, 2)),
  page_count         integer NOT NULL DEFAULT 0 CHECK (page_count >= 0),
  status             text NOT NULL DEFAULT 'processing'
                     CHECK (status IN ('processing', 'ready', 'ready_with_gaps', 'failed')),
  source             text NOT NULL DEFAULT 'upload' CHECK (source IN ('upload', 'sales_copy', 'owner_answers')),
  source_document_id uuid,
  text_layer_trusted boolean,
  crashed_passes     smallint NOT NULL DEFAULT 0 CHECK (crashed_passes >= 0),
  error              text CHECK (error IS NULL OR length(error) <= 500),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_documents_collection_idx
  ON companion_kb_documents (tenant_id, collection_id, created_at DESC);
-- The every-minute reading job looks for unfinished books, the one touched longest ago first
-- (every pass touches its book, so one that keeps failing cannot hide newer books).
CREATE INDEX IF NOT EXISTS companion_kb_documents_processing_idx
  ON companion_kb_documents (updated_at) WHERE status = 'processing';

CREATE TABLE IF NOT EXISTS companion_kb_pages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES companion_kb_documents(id) ON DELETE CASCADE,
  page_no     integer NOT NULL CHECK (page_no >= 1),
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ok', 'failed')),
  method      text CHECK (method IS NULL OR method IN ('text_layer', 'ocr')),
  attempts    smallint NOT NULL DEFAULT 0,
  char_count  integer NOT NULL DEFAULT 0,
  text        text,
  error       text CHECK (error IS NULL OR length(error) <= 500),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, page_no)
);
CREATE INDEX IF NOT EXISTS companion_kb_pages_status_idx
  ON companion_kb_pages (tenant_id, document_id, status);

CREATE TABLE IF NOT EXISTS companion_kb_chunks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  document_id     uuid NOT NULL REFERENCES companion_kb_documents(id) ON DELETE CASCADE,
  collection_id   uuid NOT NULL REFERENCES companion_kb_collections(id) ON DELETE CASCADE,
  tier            smallint NOT NULL CHECK (tier IN (1, 2)),
  seq             integer NOT NULL DEFAULT 0,
  heading_path    text NOT NULL DEFAULT '' CHECK (length(heading_path) <= 500),
  text            text NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 8000),
  page_from       integer NOT NULL CHECK (page_from >= 1),
  page_to         integer NOT NULL CHECK (page_to >= page_from),
  embedding       vector(768),
  embedding_model text,
  signposts_at    timestamptz,
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', heading_path || ' ' || text)) STORED,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_chunks_scope_idx
  ON companion_kb_chunks (tenant_id, collection_id, tier);
CREATE INDEX IF NOT EXISTS companion_kb_chunks_document_idx
  ON companion_kb_chunks (document_id, seq);

CREATE TABLE IF NOT EXISTS companion_kb_chunk_questions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  chunk_id        uuid NOT NULL REFERENCES companion_kb_chunks(id) ON DELETE CASCADE,
  collection_id   uuid NOT NULL REFERENCES companion_kb_collections(id) ON DELETE CASCADE,
  question_en     text NOT NULL DEFAULT '' CHECK (length(question_en) <= 500),
  question_ta     text NOT NULL DEFAULT '' CHECK (length(question_ta) <= 500),
  embedding       vector(768),
  embedding_model text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_kb_chunk_questions_scope_idx
  ON companion_kb_chunk_questions (tenant_id, collection_id);
CREATE INDEX IF NOT EXISTS companion_kb_chunk_questions_chunk_idx
  ON companion_kb_chunk_questions (chunk_id);

ALTER TABLE companion_kb_collections     ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_documents       ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_pages           ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_chunks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_kb_chunk_questions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON companion_kb_collections     FROM anon, authenticated;
REVOKE ALL ON companion_kb_documents       FROM anon, authenticated;
REVOKE ALL ON companion_kb_pages           FROM anon, authenticated;
REVOKE ALL ON companion_kb_chunks          FROM anon, authenticated;
REVOKE ALL ON companion_kb_chunk_questions FROM anon, authenticated;

-- The one change to an existing table: a new nullable column.
ALTER TABLE companions
  ADD COLUMN IF NOT EXISTS knowledge_collection_id uuid
    REFERENCES companion_kb_collections(id) ON DELETE SET NULL;

-- One empty collection per tag a character points at today, then point the character at it.
INSERT INTO companion_kb_collections (tenant_id, name)
SELECT DISTINCT c.tenant_id, left(btrim(t.name), 80)
FROM companions c
JOIN broadcast_tags t ON t.id = c.knowledge_tag_id AND t.tenant_id = c.tenant_id
WHERE c.knowledge_tag_id IS NOT NULL AND length(btrim(t.name)) > 0
ON CONFLICT (tenant_id, name) DO NOTHING;

UPDATE companions c
SET knowledge_collection_id = k.id
FROM broadcast_tags t
JOIN companion_kb_collections k ON k.tenant_id = t.tenant_id AND k.name = left(btrim(t.name), 80)
WHERE t.id = c.knowledge_tag_id AND t.tenant_id = c.tenant_id
  AND c.knowledge_collection_id IS NULL;

-- Private bucket: no storage policies, so only the backend's service-role key reads or writes.
-- The browser uploads through a short-lived signed upload link the backend hands out.
-- file_size_limit is the hard cap: storage itself refuses a bigger upload, so the limit does not
-- depend on what the browser claims. Keep it equal to MAX_BYTES in app/companion/kb/filetypes.py (50 MB).
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('companion-kb-documents', 'companion-kb-documents', false, 52428800)
ON CONFLICT (id) DO NOTHING;
