-- Migration: 350_message_template_text
-- Created: 2026-11-26
-- Description: The chat shows a sent template's words instead of "[Template: name]".
-- content keeps the marker: the inbox functions, search and AI context read it to spot template sends.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS template_text text;
COMMENT ON COLUMN messages.template_text IS 'The filled-in wording of a sent WhatsApp template; content keeps the [Template: name] marker.';
