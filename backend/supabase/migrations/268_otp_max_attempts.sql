-- 268_otp_max_attempts.sql
-- Wrong tries allowed before an Anril-made code locks: client-chosen (was fixed at 5).
-- Read at verify time, so a saved change also applies to codes still open. Additive only.
SET LOCAL lock_timeout = '5s';
ALTER TABLE otp_settings
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10);
