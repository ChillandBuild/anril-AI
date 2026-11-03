-- 243_sms_operator_alerts.sql
-- Two operator-bell alerts for the SMS redesign: a client uploaded PE-TM proof, a client asked
-- for SMS credit. The bell (GET /operator/alerts) reads incidents from the last 48 hours.

SET LOCAL lock_timeout = '5s';

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_type_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_type_check CHECK (type IN (
  'quality_yellow', 'quality_red', 'failover', 'migration_sent', 'appeal_filed', 'standby_promoted',
  'warm_up_complete', 'token_invalid', 'webhook_unhealthy', 'number_recovered',
  'sms_pe_tm_proof', 'sms_credit_request'
));
