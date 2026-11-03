-- 241_sms_campaign_consent.sql
-- - sms_campaigns.consent_source: for a promotional campaign to pasted numbers (source=numbers),
--   who ticked "everyone on this list agreed to promotional SMS" and when. Leads and contacts
--   carry their own consent, so it stays NULL for them.
-- - sms_contact_field_keys: the extra upload columns (sms_contacts.fields keys) of the given
--   groups, so the campaign composer can offer them as template variables. Service role only.

SET LOCAL lock_timeout = '5s';

ALTER TABLE sms_campaigns ADD COLUMN IF NOT EXISTS consent_source text;

CREATE OR REPLACE FUNCTION sms_contact_field_keys(p_tenant uuid, p_groups uuid[])
RETURNS TABLE (key text)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public AS $$
  SELECT DISTINCT k.key
  FROM sms_contacts c, LATERAL jsonb_object_keys(c.fields) AS k(key)
  WHERE c.tenant_id = p_tenant AND c.group_ids && p_groups
  ORDER BY 1
  LIMIT 50;
$$;

REVOKE EXECUTE ON FUNCTION sms_contact_field_keys(uuid, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION sms_contact_field_keys(uuid, uuid[]) TO service_role;
