-- 263: after an owner deletes a memory, no character reads that person's chat from before the delete.
--
-- Example: the owner of AstroTamil deletes Priya's fact "Amma has a sugar problem" at 10:00.
-- The backend cuts her exact words out of her saved messages and sets chat_read_after = 10:00.
-- From then on Guru's reply window holds only messages after 10:00, and Guru's own older lines
-- ("sorry about amma's sugar") are left out of the search index and the diary.
-- NULL = no memory was ever deleted for this person (everything is read, as before).
-- Apply BEFORE deploying the backend that reads the column.
ALTER TABLE companion_end_users ADD COLUMN IF NOT EXISTS chat_read_after timestamptz;

COMMENT ON COLUMN companion_end_users.chat_read_after IS
  'Set when the owner deletes a memory of this person: chat from before this moment is not read by any character.';

-- Five operator-bell alerts for companion memory (app/companion/alerts.py). The bell reads `incidents`;
-- its type check lists every allowed kind, so the new kinds are added to the list (same 12 as 243 + 5).
-- Example: Guru's note-writer fails 3 nights for AstroTamil -> one 'companion_memory_parked' row that day.
SET LOCAL lock_timeout = '5s';
ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_type_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_type_check CHECK (type IN (
  'quality_yellow', 'quality_red', 'failover', 'migration_sent', 'appeal_filed', 'standby_promoted',
  'warm_up_complete', 'token_invalid', 'webhook_unhealthy', 'number_recovered',
  'sms_pe_tm_proof', 'sms_credit_request',
  'companion_memory_parked', 'companion_memory_parked_dead', 'companion_memory_cleanup_gave_up',
  'companion_memory_delete_incomplete', 'companion_memory_fact_ceiling'
));

-- While the cleanup after an owner delete is still waiting or running, replies for that person get the
-- memory card only. companion_day_context (256) gains one key, "cleaning": true when ANY character's
-- state row for this person has a cleanup queued (forget_pending). The backend then leaves out
-- "Earlier today", "Recent days" and the old-chat search until the cleanup has finished.
-- Example: the owner deletes Priya's "Amma has a sugar problem" at 10:00. The diary line of 9 Nov that
-- says "Priya was worried about amma's sugar" is rewritten by an AI call a few seconds later (or hours
-- later if the AI provider is down). Until then cleaning = true, so Guru never sees that line.
-- Same arguments and return type as 256, so CREATE OR REPLACE keeps its grants (service_role only).
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
    'cleaning', EXISTS (SELECT 1 FROM companion_memory_state
                        WHERE tenant_id = p_tenant AND end_user_id = p_end_user AND forget_pending IS NOT NULL),
    'diary', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('day', d.day, 'text', d.text) ORDER BY d.day DESC)
      FROM (SELECT day, text FROM companion_memory_diary
            WHERE tenant_id = p_tenant AND companion_id = p_companion AND end_user_id = p_end_user
              AND day < p_before_day
            ORDER BY day DESC LIMIT p_days) d), '[]'::jsonb));
$$;
