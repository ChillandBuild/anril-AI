-- v9.2 #216: the course waitlist is told when a seat frees.
--   source    who added the person: staff (Courses page) or ai (the AI agent in chat, tool join_batch_waitlist)
--   told_at   when we told them a seat is free (the 15-minute job, services/courses.tell_waitlists)
--   told_via  text (inside the 24-hour window) · template (approved batch_seat_free) · staff (no WhatsApp way: a bell
--             asks the team to call)
-- A told row that is still on the list holds its seat for 48 hours, so one free seat is never offered to two people.
ALTER TABLE public.batch_waitlist
  ADD COLUMN IF NOT EXISTS source   text NOT NULL DEFAULT 'staff',
  ADD COLUMN IF NOT EXISTS told_at  timestamptz,
  ADD COLUMN IF NOT EXISTS told_via text;

DO $$ BEGIN
  ALTER TABLE public.batch_waitlist ADD CONSTRAINT batch_waitlist_source_check CHECK (source IN ('staff', 'ai'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.batch_waitlist ADD CONSTRAINT batch_waitlist_told_via_check
    CHECK (told_via IS NULL OR told_via IN ('text', 'template', 'staff'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_batch_waitlist_untold ON public.batch_waitlist (created_at) WHERE told_at IS NULL;
