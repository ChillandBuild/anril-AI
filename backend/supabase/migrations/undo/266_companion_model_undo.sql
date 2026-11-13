-- Undo for 266_companion_model.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Roll the backend back first: the newer backend reads and writes companions.model.
-- After this, every character answers with the business's ai_reply_model again.
alter table public.companions drop column if exists model;
