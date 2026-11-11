-- Undo for 260_companion_kb_learning.sql. NOT a migration: run by hand in the Supabase SQL Editor.
-- Deletes the question log, every learned shortcut and the gap list.
DROP FUNCTION IF EXISTS companion_kb_question_tenants();
DROP TABLE IF EXISTS companion_kb_gaps;
DROP TABLE IF EXISTS companion_kb_shortcuts;
DROP TABLE IF EXISTS companion_kb_question_log;
