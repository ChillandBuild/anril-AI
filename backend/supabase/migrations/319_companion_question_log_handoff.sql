-- 319: the question log also records "handoff" answers (the chart guard stopped a reply, or the character
-- handed the question to a person). Like "own", a handoff is a question no file answered, so it goes on the
-- owner's Missing answers list right away (kb/learning.log_question). Undo: undo/319_companion_question_log_handoff_undo.sql
ALTER TABLE public.companion_kb_question_log DROP CONSTRAINT IF EXISTS companion_kb_question_log_basis_check;
ALTER TABLE public.companion_kb_question_log ADD CONSTRAINT companion_kb_question_log_basis_check
  CHECK (basis IN ('primary', 'book', 'own', 'handoff'));
