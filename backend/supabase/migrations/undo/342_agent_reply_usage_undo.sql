-- Undo 342: no add_usage, no agent_replies item, metric list back to 218's. Run only after deleting any
-- tenant_usage_counters rows with metric 'agent_reply' and tenant_subscription_items rows 'agent_replies'.
SET LOCAL lock_timeout = '5s';
DROP FUNCTION IF EXISTS public.add_usage(uuid, text, text, integer, integer);
DELETE FROM feature_catalog WHERE feature_key = 'agent_replies';
ALTER TABLE tenant_usage_counters DROP CONSTRAINT IF EXISTS tenant_usage_counters_metric_check;
ALTER TABLE tenant_usage_counters ADD CONSTRAINT tenant_usage_counters_metric_check
  CHECK (metric IN (
    'message_sent', 'ai_reply', 'call_minute', 'team_seat_active', 'storage_gb',
    'ai_call_summary', 'ai_call_scoring', 'phone_number',
    'ai_speech_to_text', 'ai_text_to_speech',
    'private_send_message'
  ));
