-- 212_intake_deal_lifecycle.sql
-- Deal lifecycle (.agents/decisions/log.md 2026-09-30, R2 + R3):
--   last_activity_at         reset only by a lead message or real deal progress; the idle-close
--                            sweep measures from here (updated_at is never written).
--   razorpay_payment_link_id the CURRENT plink, so an old link can be cancelled on Razorpay and
--                            webhooks for a replaced link can be ignored.
--   refund_needed            a second payment landed on an already-paid deal; staff refund by hand.
--   extra_payment_ids        the Razorpay payment ids of those extra payments.
-- Additive only. Apply BEFORE the new code deploys (the code writes these columns).
-- The one-open-deal-per-lead unique index is 213, applied after the close path ships.

ALTER TABLE intake_sessions
  ADD COLUMN IF NOT EXISTS last_activity_at timestamptz,
  ADD COLUMN IF NOT EXISTS razorpay_payment_link_id text,
  ADD COLUMN IF NOT EXISTS refund_needed boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS extra_payment_ids text[] NOT NULL DEFAULT '{}';

UPDATE intake_sessions SET last_activity_at = created_at WHERE last_activity_at IS NULL;

NOTIFY pgrst, 'reload schema';
