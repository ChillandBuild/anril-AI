-- 249_companion_memory.sql
-- Aira Companion Level 2 memory (spec: docs/superpowers/specs/2026-11-09-companion-memory-design.md).
--
-- - companions.memory_engine: which Level 2 engine a character uses ('card' = ours, 'mem0').
--   Ignored at memory_level 1.
-- - companions.history_messages: how many recent messages every reply reads (default 10, 2-50).
--   Used at every memory level.
-- - companion_tenant_settings: one row per business. memory_scope = 'character' (each character
--   remembers only what it was told) or 'business' (characters share what the person told any
--   of them). No row = 'character'.
-- - companion_memory_facts: the card engine's facts, one row per fact so one fact can be listed
--   or forgotten on its own. companion_id = the character that LEARNED the fact; scope is applied
--   on read, so switching memory_scope moves no data. A fact that stops being true is closed
--   (status 'closed', valid_to set), never overwritten. updated_at doubles as "closed at" for the
--   90-day window in which closed facts are still shown to the character.
-- - companion_memory_state: per (character, person) watermark = created_at of the newest message
--   already turned into memory. The nightly sweep (02:00 IST) reads messages after it.
--   failures = nights in a row the sweep failed for this pair; the 3rd moves the watermark on.
--
-- RLS on with no policies: service role only, like 248. No operator route reads these tables.

SET LOCAL lock_timeout = '5s';

ALTER TABLE companions
  ADD COLUMN IF NOT EXISTS memory_engine text NOT NULL DEFAULT 'card'
  CHECK (memory_engine IN ('card', 'mem0'));

ALTER TABLE companions
  ADD COLUMN IF NOT EXISTS history_messages int NOT NULL DEFAULT 10
  CHECK (history_messages BETWEEN 2 AND 50);

CREATE TABLE IF NOT EXISTS companion_tenant_settings (
  tenant_id    uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  memory_scope text NOT NULL DEFAULT 'character' CHECK (memory_scope IN ('character', 'business')),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS companion_memory_facts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id  uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  section      text NOT NULL CHECK (section IN ('profile', 'people', 'life', 'preferences', 'threads')),
  text         text NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 300),
  valid_from   date,
  valid_to     date,
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_memory_facts_person_idx
  ON companion_memory_facts (tenant_id, end_user_id, status);

CREATE TABLE IF NOT EXISTS companion_memory_state (
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id     uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  last_message_at timestamptz,
  failures        int NOT NULL DEFAULT 0 CHECK (failures >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (companion_id, end_user_id)
);

ALTER TABLE companion_tenant_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_memory_facts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_memory_state    ENABLE ROW LEVEL SECURITY;
