-- Undo 319: handoff rows become own first, so the old check can come back.
UPDATE public.companion_kb_question_log SET basis = 'own' WHERE basis = 'handoff';
ALTER TABLE public.companion_kb_question_log DROP CONSTRAINT IF EXISTS companion_kb_question_log_basis_check;
ALTER TABLE public.companion_kb_question_log ADD CONSTRAINT companion_kb_question_log_basis_check
  CHECK (basis IN ('primary', 'book', 'own'));
