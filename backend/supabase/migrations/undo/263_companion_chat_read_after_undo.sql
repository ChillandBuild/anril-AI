-- Undo for 263_companion_chat_read_after.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Roll the backend back first: the newer backend reads and writes chat_read_after.
-- After this, characters read the chat from before an owner delete again.
ALTER TABLE companion_end_users DROP COLUMN IF EXISTS chat_read_after;

-- The alert kinds: delete the companion memory alerts, then put the 243 list back.
DELETE FROM incidents WHERE type LIKE 'companion_memory_%';
ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_type_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_type_check CHECK (type IN (
  'quality_yellow', 'quality_red', 'failover', 'migration_sent', 'appeal_filed', 'standby_promoted',
  'warm_up_complete', 'token_invalid', 'webhook_unhealthy', 'number_recovered',
  'sms_pe_tm_proof', 'sms_credit_request'
));

-- companion_day_context back to its 256 body (no "cleaning" key).
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
