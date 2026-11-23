-- Undo 340. Liked-reply rows are removed first, or the old kind check would fail.
DROP INDEX IF EXISTS public.ai_teach_items_message_uq;
ALTER TABLE public.ai_teach_items DROP COLUMN IF EXISTS message_id;
DELETE FROM public.ai_teach_items WHERE kind = 'liked';
ALTER TABLE public.ai_teach_items DROP CONSTRAINT IF EXISTS ai_teach_items_kind_check;
ALTER TABLE public.ai_teach_items ADD CONSTRAINT ai_teach_items_kind_check CHECK (kind IN ('answer', 'word'));
ALTER TABLE public.leads DROP COLUMN IF EXISTS detail_sources;
