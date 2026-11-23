-- 322: Anril Setup (v9.2 #23).
--   ai_reply_feedback          a thumbs-down on one AI reply in Chats, with a reason. One per person per reply.
--   chat_handovers.answered_at set when the owner answers that "couldn't answer" question in Anril Setup,
--                              so the question stops showing in Couldn't answer.
-- RLS on, no policies, on the new table: backend service key only. Additive.
-- Undo: undo/322_ai_setup_feedback_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.ai_reply_feedback (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  message_id  uuid NOT NULL,
  lead_id     uuid,
  reason      text NOT NULL CHECK (reason IN ('wrong', 'rude', 'too_long', 'other')),
  note        text CHECK (note IS NULL OR length(note) <= 300),
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_reply_feedback_msg_user_uq ON public.ai_reply_feedback (message_id, created_by);
CREATE INDEX IF NOT EXISTS ai_reply_feedback_tenant_idx ON public.ai_reply_feedback (tenant_id, created_at DESC);
ALTER TABLE public.ai_reply_feedback ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.chat_handovers ADD COLUMN IF NOT EXISTS answered_at timestamptz;
