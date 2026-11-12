-- Undo for 262_companion_memory_slots_threads_links.sql. NOT a migration: run by hand in the Supabase
-- SQL Editor. Roll the backend back first: the newer backend calls companion_set_slot_fact and writes
-- slot / asked_at / expired_at. Deletes every saved slot name and thread follow-up mark.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['companion_memory_facts', 'companion_memory_state', 'companion_memory_diary',
                           'companion_memory_chunks'] LOOP
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_tenant_end_user_fkey');
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_tenant_companion_fkey');
  END LOOP;
END;
$$;
ALTER TABLE companions DROP CONSTRAINT IF EXISTS companions_tenant_id_id_key;
ALTER TABLE companion_end_users DROP CONSTRAINT IF EXISTS companion_end_users_tenant_id_id_key;
DROP FUNCTION IF EXISTS companion_set_slot_fact(uuid, uuid, uuid, text, text, text, date, date, text, uuid);
DROP INDEX IF EXISTS companion_memory_facts_slot_key;
ALTER TABLE companion_memory_facts
  DROP COLUMN IF EXISTS expired_at,
  DROP COLUMN IF EXISTS asked_at,
  DROP COLUMN IF EXISTS slot;
