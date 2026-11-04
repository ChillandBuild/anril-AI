-- 245_sms_send_response.sql
-- Bulk9's reply to each send (financial fields already scrubbed by bulk9_client.send_dlt), kept so a
-- message that is "Sent to operator" but never delivered can be traced. On 2026-11-04 three API
-- sends were accepted and charged but held by Bulk9 until 10 AM, and Anril had no record of what
-- Bulk9 actually answered. Additive and nullable: older rows stay NULL.

ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS send_response jsonb;
