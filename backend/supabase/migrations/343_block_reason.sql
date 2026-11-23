-- 343_block_reason.sql  (v9.2 Chats > Archived: why a contact was blocked)
-- Additive only. Archive already has archived_reason (auto codes idle_30d / order_delivered, or the
-- teammate's typed "Why"); this adds the same for Block: "Spam links", "Abuse", or typed text.
-- Undo: undo/343_block_reason_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS blocked_reason text
  CHECK (blocked_reason IS NULL OR length(blocked_reason) <= 120);
COMMENT ON COLUMN public.leads.blocked_reason IS 'Why the team blocked this contact (typed or a chip). Cleared on Unblock.';
