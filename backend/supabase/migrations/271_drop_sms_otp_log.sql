-- 271_drop_sms_otp_log.sql
-- Bulk9 Smart OTP is removed (2026-11-15); Anril OTP (otp_requests, 267) replaced it.
-- sms_otp_log was its history table and never held a row. Apply after the backend that no
-- longer reads it is deployed (the old backend's OTP history and SMS dashboard query it).
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS sms_otp_log;
