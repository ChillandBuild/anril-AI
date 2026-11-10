-- 255_companion_memory_recap_diary.sql
-- Aira Companion Level 2 memory, card engine: same-day recap + diary lines (Instinct-style).
--
-- - companion_memory_state.today_recap: a short "earlier today" note per (character, person),
--   written by the same-day refresh when the chat outgrows history_messages. Bullet lines, at most
--   1,500 characters. Used in the prompt only on recap_day (IST). recap_through = created_at of the
--   newest message the recap covers. The nightly sweep turns it into a diary line and clears it.
--   Example: "- Interview at Infosys 3 pm, Whitefield office; nervous".
-- - companion_memory_diary: one line per (character, person, IST day), written by the 02:00 sweep.
--   The last 5 days go into the prompt; rows older than 90 days are pruned by the sweep.
--   Example: day 2026-11-10, "Infosys interview went okay, waiting for result; worried about mom's fever."
--
-- RLS on with no policies: service role only, like 248. No operator route reads this table yet.

SET LOCAL lock_timeout = '5s';

ALTER TABLE companion_memory_state
  ADD COLUMN IF NOT EXISTS today_recap text CHECK (char_length(today_recap) <= 1500),
  ADD COLUMN IF NOT EXISTS recap_day date,
  ADD COLUMN IF NOT EXISTS recap_through timestamptz;

CREATE TABLE IF NOT EXISTS companion_memory_diary (
  companion_id uuid NOT NULL REFERENCES companions(id) ON DELETE CASCADE,
  end_user_id  uuid NOT NULL REFERENCES companion_end_users(id) ON DELETE CASCADE,
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  day          date NOT NULL,
  text         text NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 300),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (companion_id, end_user_id, day)
);
CREATE INDEX IF NOT EXISTS companion_memory_diary_person_idx
  ON companion_memory_diary (tenant_id, end_user_id);

ALTER TABLE companion_memory_diary ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON companion_memory_diary FROM anon, authenticated;
