-- Undo 267_anril_otp.sql. Drops every OTP table (history, keys, settings, pending updates).
DROP FUNCTION IF EXISTS otp_try_code(uuid, uuid, text, integer);
DROP TABLE IF EXISTS otp_status_events;
DROP TABLE IF EXISTS otp_requests;
DROP TABLE IF EXISTS otp_api_keys;
DROP TABLE IF EXISTS otp_settings;
