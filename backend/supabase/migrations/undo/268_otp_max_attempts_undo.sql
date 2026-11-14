-- Undo 268_otp_max_attempts.sql
ALTER TABLE otp_settings DROP COLUMN IF EXISTS max_attempts;
