-- Undo 298. Rows marked 'no_consent' go back to 'failed' so the old CHECK accepts them.
UPDATE meta_form_leads SET template_status = 'failed' WHERE template_status = 'no_consent';
ALTER TABLE meta_form_leads DROP CONSTRAINT IF EXISTS meta_form_leads_template_status_check;
ALTER TABLE meta_form_leads ADD CONSTRAINT meta_form_leads_template_status_check CHECK (template_status IN (
  'pending', 'sending', 'sent', 'failed', 'no_template', 'no_phone', 'skipped_old'
));
ALTER TABLE meta_form_leads DROP COLUMN IF EXISTS whatsapp_consent;
ALTER TABLE meta_lead_forms DROP COLUMN IF EXISTS template_audience;
