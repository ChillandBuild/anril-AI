-- Undo 299. 'saved' answers go back to 'received' so the old CHECK accepts them.
UPDATE whatsapp_form_responses SET outcome = 'received' WHERE outcome = 'saved';
ALTER TABLE whatsapp_form_responses DROP CONSTRAINT IF EXISTS whatsapp_form_responses_outcome_check;
ALTER TABLE whatsapp_form_responses ADD CONSTRAINT whatsapp_form_responses_outcome_check
  CHECK (outcome IN ('received', 'link_sent', 'continued_in_chat', 'rejected'));
DROP INDEX IF EXISTS whatsapp_forms_design_idx;
ALTER TABLE whatsapp_forms DROP COLUMN IF EXISTS design_id;
DROP TABLE IF EXISTS whatsapp_form_designs;
