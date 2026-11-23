DROP INDEX IF EXISTS public.idx_batch_waitlist_untold;
ALTER TABLE public.batch_waitlist DROP CONSTRAINT IF EXISTS batch_waitlist_told_via_check;
ALTER TABLE public.batch_waitlist DROP CONSTRAINT IF EXISTS batch_waitlist_source_check;
ALTER TABLE public.batch_waitlist DROP COLUMN IF EXISTS told_via, DROP COLUMN IF EXISTS told_at, DROP COLUMN IF EXISTS source;
