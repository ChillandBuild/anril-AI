-- 248_companion_core.sql
-- Aira Companion core: characters a business sets up, the people who talk to them, and the chats.
--
-- - companions: one row per CHARACTER (a tenant can have several, e.g. "Jothidar AI" and
--   "Vastu Guru"). Holds the character card (role, backstory, speaking style, sample lines,
--   goals, temperament, default mood), business rules, and knowledge_tag_id, which scopes the
--   character's books through knowledge_documents.campaign_tag_id (null = every book).
-- - companion_end_users: one row per PERSON per business, shared by all its characters.
--   external_user_id is the client's own user id. forgotten_at is set by "forget me".
-- - companion_conversations: one per (character, person); a new one opens after 24 h of silence.
--   mood = how this character currently feels toward this person.
-- - companion_messages: the chat. content has the [mood: X] tag stripped. tool_calls keeps the
--   names and args of app-run tools, never their outputs.
-- - companion_pending_turns: a reply paused while the client's app runs a tool. Lives for at
--   most 2 minutes; the backend sweeps expired rows on every create and continue (no cron).
--
-- Platform rules and the mood list live in code (app/companion/platform_rules.py), not here.
-- RLS on with no policies: service role only, like 240. No operator route reads these tables.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS companions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name             text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  industry         text NOT NULL DEFAULT 'general' CHECK (industry IN ('astrology', 'general')),
  role             text NOT NULL DEFAULT '' CHECK (length(role) <= 500),
  backstory        text NOT NULL DEFAULT '' CHECK (length(backstory) <= 2000),
  speaking_style   text NOT NULL DEFAULT '' CHECK (length(speaking_style) <= 1000),
  sample_lines     text[] NOT NULL DEFAULT '{}' CHECK (cardinality(sample_lines) <= 10),
  goals            text[] NOT NULL DEFAULT '{}' CHECK (cardinality(goals) <= 5),
  temperament      text NOT NULL DEFAULT '' CHECK (length(temperament) <= 300),
  default_mood     text NOT NULL DEFAULT 'calm'
                   CHECK (default_mood IN ('calm', 'warm', 'happy', 'concerned', 'encouraging', 'serious')),
  language         text NOT NULL DEFAULT 'ta-en' CHECK (length(language) BETWEEN 1 AND 16),
  rules            text[] NOT NULL DEFAULT '{}' CHECK (cardinality(rules) <= 30),
  knowledge_tag_id uuid REFERENCES broadcast_tags(id) ON DELETE SET NULL,
  memory_level     smallint NOT NULL DEFAULT 1 CHECK (memory_level IN (1, 2, 3)),
  privacy_mode     text NOT NULL DEFAULT 'A' CHECK (privacy_mode IN ('A', 'B')),
  status           text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'live', 'paused')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS companion_end_users (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  external_user_id text NOT NULL CHECK (length(external_user_id) BETWEEN 1 AND 200),
  display_name     text CHECK (length(display_name) <= 100),
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  forgotten_at     timestamptz,
  UNIQUE (tenant_id, external_user_id)
);

CREATE TABLE IF NOT EXISTS companion_conversations (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id     uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  mood            text NOT NULL DEFAULT 'calm',
  started_at      timestamptz NOT NULL DEFAULT now(),
  last_message_at timestamptz NOT NULL DEFAULT now(),
  message_count   integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS companion_conversations_pair_idx
  ON companion_conversations (companion_id, end_user_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS companion_messages (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL REFERENCES companion_conversations(id) ON DELETE CASCADE,
  end_user_id     uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user', 'assistant')),
  content         text NOT NULL CHECK (length(content) <= 8000),
  mood            text,
  tool_calls      jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_messages_conversation_idx
  ON companion_messages (conversation_id, created_at);
-- Level 1 history reads the last messages of one (character, person) pair across conversations.
CREATE INDEX IF NOT EXISTS companion_messages_pair_idx
  ON companion_messages (companion_id, end_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS companion_pending_turns (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  companion_id    uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL REFERENCES companion_conversations(id) ON DELETE CASCADE,
  messages        jsonb NOT NULL,
  tools           jsonb NOT NULL DEFAULT '[]'::jsonb,
  round           smallint NOT NULL DEFAULT 1 CHECK (round BETWEEN 1 AND 3),
  expires_at      timestamptz NOT NULL DEFAULT now() + interval '2 minutes',
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companion_pending_turns_expires_idx ON companion_pending_turns (expires_at);

ALTER TABLE companions              ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_end_users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_pending_turns ENABLE ROW LEVEL SECURITY;
