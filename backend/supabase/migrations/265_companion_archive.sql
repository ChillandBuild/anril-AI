-- Archive for Anril Agents characters.
-- Empty = active. A date = archived at that moment: hidden from the Characters list (it shows in the
-- Archived tab), status set to 'paused' so it stops answering at once. Restore clears it and sets 'draft'.
-- Delete permanently removes the row; every companion_* child table already cascades.
-- Example: archive Jothidar AI on 13 Nov 2026 → archived_at = 2026-11-13T16:40Z, status = 'paused'.
alter table public.companions add column if not exists archived_at timestamptz;

comment on column public.companions.archived_at is
  'When the owner archived this character. NULL = active. Restore sets it back to NULL with status draft.';
