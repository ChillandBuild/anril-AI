-- Undo 334. Drops the three columns (the data in them is lost).
alter table public.telecalling_upload_batches
  drop column if exists taken_out_counts,
  drop column if exists taken_out;

alter table public.call_logs
  drop column if exists booking_id;
