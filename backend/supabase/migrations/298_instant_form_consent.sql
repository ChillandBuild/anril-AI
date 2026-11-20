-- 298: Meta Instant Forms — WhatsApp consent per lead, and who gets the form's template.
--
-- * meta_lead_forms.template_audience: 'everyone' (default; how it worked before) or
--   'consented' (only people who ticked the form's consent checkbox, or answered yes to a
--   question about WhatsApp). Chosen per form, next to the template.
-- * meta_form_leads.whatsapp_consent: true = ticked / said yes, false = left it unticked,
--   NULL = the form asks nothing we can read as WhatsApp consent.
-- * template_status 'no_consent': not sent because the form sends only to people who agreed.
--   The owner's Resend still sends it (their explicit choice).
-- Existing leads are untouched (decided 2026-11-20: option B).

ALTER TABLE meta_lead_forms ADD COLUMN IF NOT EXISTS template_audience text NOT NULL DEFAULT 'everyone'
  CHECK (template_audience IN ('everyone', 'consented'));

ALTER TABLE meta_form_leads ADD COLUMN IF NOT EXISTS whatsapp_consent boolean;

ALTER TABLE meta_form_leads DROP CONSTRAINT IF EXISTS meta_form_leads_template_status_check;
ALTER TABLE meta_form_leads ADD CONSTRAINT meta_form_leads_template_status_check CHECK (template_status IN (
  'pending', 'sending', 'sent', 'failed', 'no_template', 'no_phone', 'skipped_old', 'no_consent'
));
