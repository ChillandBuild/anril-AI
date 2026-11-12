-- 262_companion_memory_slots_threads_links.sql
-- Aira Companion Level 2 memory: one live fact per slot, thread follow-up, and tenant links.
--
-- 1. companion_memory_facts.slot: what a profile fact IS ("home_city", "job"; the list lives in
--    memory_card.SLOTS). A (character, person) pair holds at most ONE active fact per slot: the partial
--    unique index enforces it. Example, Priya with Guru: "Lives in Chennai" (slot home_city) is active;
--    she says she moved; companion_set_slot_fact closes it (valid_to = the move date) and inserts
--    "Lives in Bengaluru" in the same transaction, so the card never shows two home cities and never
--    loses the fact halfway. NULL = a fact with no slot (most facts).
-- 2. Threads ("Zoho interview", section 'threads'): valid_from is the day the thing happens.
--    asked_at   = when the character was shown the thread as due (it asks once, then waits).
--    expired_at = the nightly job gave up on it (7 days past its date, or 30 days old with no date);
--                 the row is also set to status 'closed' and is no longer shown to the character.
-- 3. Tenant links: a memory row's (tenant_id, end_user_id) and (tenant_id, companion_id) must be a
--    real person and a real character OF THAT SAME BUSINESS. Before this, the foreign keys checked
--    only the ids, so a bug could save business A's memory against business B's person.
--
-- Add-only: three nullable columns, one index, one function, two unique constraints, eight foreign
-- keys. No data change. The four memory tables were empty when this was written (2026-11-11), so the
-- new foreign keys validate instantly. RLS of every table is unchanged.
-- Must be applied BEFORE the backend that writes these columns is deployed.

ALTER TABLE companion_memory_facts
  ADD COLUMN IF NOT EXISTS slot text CHECK (slot IS NULL OR char_length(slot) BETWEEN 1 AND 40),
  ADD COLUMN IF NOT EXISTS asked_at timestamptz,
  ADD COLUMN IF NOT EXISTS expired_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS companion_memory_facts_slot_key
  ON companion_memory_facts (tenant_id, companion_id, end_user_id, slot)
  WHERE status = 'active' AND slot IS NOT NULL;


-- Closes this pair's active fact in p_slot (if any) and inserts the new one, in one transaction.
-- {"fact": <the new row>, "closed": [<rows it closed>]}
CREATE OR REPLACE FUNCTION companion_set_slot_fact(
  p_tenant uuid, p_companion uuid, p_end_user uuid, p_slot text, p_section text, p_text text,
  p_valid_from date, p_closed_on date, p_quote text, p_source uuid)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  old_rows jsonb;
  new_row  companion_memory_facts;
BEGIN
  WITH closed AS (
    UPDATE companion_memory_facts
       SET status = 'closed', valid_to = p_closed_on, updated_at = now()
     WHERE tenant_id = p_tenant AND companion_id = p_companion AND end_user_id = p_end_user
       AND slot = p_slot AND status = 'active'
    RETURNING *)
  SELECT coalesce(jsonb_agg(to_jsonb(closed)), '[]'::jsonb) INTO old_rows FROM closed;

  INSERT INTO companion_memory_facts (tenant_id, companion_id, end_user_id, section, text, valid_from,
                                      status, slot, quote, source_message_id)
  VALUES (p_tenant, p_companion, p_end_user, p_section, p_text, p_valid_from, 'active', p_slot, p_quote,
          p_source)
  RETURNING * INTO new_row;

  RETURN jsonb_build_object('fact', to_jsonb(new_row), 'closed', old_rows);
END;
$$;

REVOKE ALL ON FUNCTION companion_set_slot_fact(uuid, uuid, uuid, text, text, text, date, date, text, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION companion_set_slot_fact(uuid, uuid, uuid, text, text, text, date, date, text, uuid)
  TO service_role;


-- Tenant links. A composite foreign key needs a unique (tenant_id, id) on the table it points at.
DO $$
DECLARE
  t text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'companion_end_users_tenant_id_id_key') THEN
    ALTER TABLE companion_end_users ADD CONSTRAINT companion_end_users_tenant_id_id_key UNIQUE (tenant_id, id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'companions_tenant_id_id_key') THEN
    ALTER TABLE companions ADD CONSTRAINT companions_tenant_id_id_key UNIQUE (tenant_id, id);
  END IF;
  FOREACH t IN ARRAY ARRAY['companion_memory_facts', 'companion_memory_state', 'companion_memory_diary',
                           'companion_memory_chunks'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_tenant_end_user_fkey') THEN
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, end_user_id) '
                     'REFERENCES companion_end_users (tenant_id, id) ON DELETE CASCADE',
                     t, t || '_tenant_end_user_fkey');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = t || '_tenant_companion_fkey') THEN
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, companion_id) '
                     'REFERENCES companions (tenant_id, id) ON DELETE CASCADE',
                     t, t || '_tenant_companion_fkey');
    END IF;
  END LOOP;
END;
$$;
