-- v9.2 last items (23 Nov 2026).
-- A. AI saves lead details from the chat: leads.detail_sources says who set each detail in
--    leads.collected_data ({"budget": {"by": "ai", "at": "..."}} or {"by": "staff", "name": "Karthik", ...}),
--    so the About panel can show "from chat" / "by Karthik" and the AI never writes over a staff edit.
-- B. Replies you like: ai_teach_items gets a third kind, 'liked' (customer message -> the reply the
--    owner liked), and message_id, the AI reply that was liked in Chats (one row per message).

ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS detail_sources jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.ai_teach_items DROP CONSTRAINT IF EXISTS ai_teach_items_kind_check;
ALTER TABLE public.ai_teach_items ADD CONSTRAINT ai_teach_items_kind_check
  CHECK (kind IN ('answer', 'word', 'liked'));

ALTER TABLE public.ai_teach_items ADD COLUMN IF NOT EXISTS message_id uuid
  REFERENCES public.messages(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ai_teach_items_message_uq
  ON public.ai_teach_items (tenant_id, message_id) WHERE message_id IS NOT NULL;
