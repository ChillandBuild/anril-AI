-- 240_sms_contacts.sql
-- SMS address book, manual (raw DLT ID) campaigns, and OTP delivery status.
--
-- - sms_contacts: a client's own SMS numbers, separate from leads (SMS is sold on its own).
--   One row per (tenant, 10-digit mobile). Extra upload columns live in `fields` and can fill
--   template variables. group_ids holds the groups it is in, so one person in two groups is one
--   row and gets one SMS. promo_consent_*: recorded when the uploader ticks "everyone agreed to
--   promotional SMS"; promotional campaigns skip contacts without it.
-- - sms_contact_groups: named lists ("Diwali list"); a CSV upload lands in one.
-- - sms_campaigns gains:
--     kind    template = an approved Bulk9 template (route=dlt), manual = raw DLT IDs (dlt_manual)
--     source  leads | contacts (group_ids) | numbers (pasted, `numbers`)
--     status 'preparing': a contacts campaign (up to 50,000) is built by the sms-send job, not
--     during the click; build_started_at claims the build, build_error says why it stopped.
-- - sms_messages.contact_id: who a contact campaign's SMS went to (kept NULL if they're deleted).
-- - sms_otp_log delivery columns, filled by the OTP webhook (/webhook/bulk9/{tenant}/otp).
--
-- The sms_contacts_* / sms_group_delete functions do the set-based writes PostgREST can't
-- (merge-on-upsert, array add/remove). Service role only, like 237/239.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS sms_contact_groups (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name       text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_contact_groups_name_uq ON sms_contact_groups (tenant_id, lower(btrim(name)));

CREATE TABLE IF NOT EXISTS sms_contacts (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  phone                text NOT NULL CHECK (phone ~ '^[6-9][0-9]{9}$'),
  name                 text,
  fields               jsonb NOT NULL DEFAULT '{}'::jsonb,
  group_ids            uuid[] NOT NULL DEFAULT '{}',
  promo_consent_at     timestamptz,
  promo_consent_source text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone)
);
CREATE INDEX IF NOT EXISTS sms_contacts_groups_idx ON sms_contacts USING gin (group_ids);
CREATE INDEX IF NOT EXISTS sms_contacts_tenant_created_idx ON sms_contacts (tenant_id, created_at DESC);

ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS contact_id uuid REFERENCES sms_contacts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS sms_messages_contact_idx ON sms_messages (contact_id) WHERE contact_id IS NOT NULL;

ALTER TABLE sms_campaigns ALTER COLUMN message_id DROP NOT NULL;
ALTER TABLE sms_campaigns
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'template' CHECK (kind IN ('template', 'manual')),
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'leads' CHECK (source IN ('leads', 'contacts', 'numbers')),
  ADD COLUMN IF NOT EXISTS group_ids uuid[],
  ADD COLUMN IF NOT EXISTS numbers text[],
  ADD COLUMN IF NOT EXISTS manual_entity_id text,
  ADD COLUMN IF NOT EXISTS manual_template_id text,
  ADD COLUMN IF NOT EXISTS build_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS build_error text;
ALTER TABLE sms_campaigns DROP CONSTRAINT IF EXISTS sms_campaigns_status_check;
ALTER TABLE sms_campaigns ADD CONSTRAINT sms_campaigns_status_check
  CHECK (status IN ('preparing', 'scheduled', 'sending', 'completed', 'cancelled'));
ALTER TABLE sms_campaigns DROP CONSTRAINT IF EXISTS sms_campaigns_kind_fields_check;
ALTER TABLE sms_campaigns ADD CONSTRAINT sms_campaigns_kind_fields_check CHECK (
  (kind = 'template' AND message_id IS NOT NULL)
  OR (kind = 'manual' AND manual_entity_id IS NOT NULL AND manual_template_id IS NOT NULL));
CREATE INDEX IF NOT EXISTS sms_campaigns_preparing_idx ON sms_campaigns (created_at) WHERE status = 'preparing';

ALTER TABLE sms_otp_log
  ADD COLUMN IF NOT EXISTS delivery_status text,
  ADD COLUMN IF NOT EXISTS delivered_at timestamptz,
  ADD COLUMN IF NOT EXISTS amount_debited numeric(12,4);
CREATE INDEX IF NOT EXISTS sms_otp_log_request_idx ON sms_otp_log (tenant_id, request_id) WHERE request_id IS NOT NULL;

ALTER TABLE sms_contact_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE sms_contacts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sms_contact_groups, sms_contacts FROM anon, authenticated;
GRANT ALL ON sms_contact_groups, sms_contacts TO service_role;

-- ---------------------------------------------------------------- functions

-- Insert or merge contacts. p_rows: [{"phone": "9876543210", "name": "Ravi", "fields": {...}}].
-- A repeated phone in p_rows: the last one wins. An existing contact keeps its groups and gains
-- p_group; a newer name/field value replaces the old one; consent is only ever added.
CREATE OR REPLACE FUNCTION sms_contacts_upsert(p_tenant uuid, p_rows jsonb, p_group uuid, p_consent_source text)
RETURNS TABLE (inserted int, updated int)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
BEGIN
  IF p_group IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM sms_contact_groups g WHERE g.id = p_group AND g.tenant_id = p_tenant) THEN
    RAISE EXCEPTION 'group not found' USING ERRCODE = 'P0002';
  END IF;
  RETURN QUERY
  WITH input AS (
    SELECT DISTINCT ON (e.v->>'phone')
           e.v->>'phone' AS phone, nullif(btrim(e.v->>'name'), '') AS name,
           coalesce(e.v->'fields', '{}'::jsonb) AS fields
    FROM jsonb_array_elements(p_rows) WITH ORDINALITY AS e(v, n)
    ORDER BY e.v->>'phone', e.n DESC
  ), up AS (
    INSERT INTO sms_contacts AS c (tenant_id, phone, name, fields, group_ids, promo_consent_at, promo_consent_source)
    SELECT p_tenant, i.phone, i.name, i.fields,
           CASE WHEN p_group IS NULL THEN '{}'::uuid[] ELSE ARRAY[p_group] END,
           CASE WHEN p_consent_source IS NOT NULL THEN now() END, p_consent_source
    FROM input i
    ON CONFLICT (tenant_id, phone) DO UPDATE SET
      name = coalesce(EXCLUDED.name, c.name),
      fields = c.fields || EXCLUDED.fields,
      group_ids = CASE WHEN p_group IS NULL OR p_group = ANY (c.group_ids) THEN c.group_ids
                       ELSE c.group_ids || p_group END,
      promo_consent_at = coalesce(EXCLUDED.promo_consent_at, c.promo_consent_at),
      promo_consent_source = coalesce(EXCLUDED.promo_consent_source, c.promo_consent_source),
      updated_at = now()
    RETURNING (xmax = 0) AS is_new
  )
  SELECT (count(*) FILTER (WHERE is_new))::int, (count(*) FILTER (WHERE NOT is_new))::int FROM up;
END $$;

-- Add (p_add) or remove the given contacts to/from one group. Returns contacts changed.
CREATE OR REPLACE FUNCTION sms_contacts_set_group(p_tenant uuid, p_group uuid, p_ids uuid[], p_add boolean)
RETURNS int
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE n int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM sms_contact_groups g WHERE g.id = p_group AND g.tenant_id = p_tenant) THEN
    RAISE EXCEPTION 'group not found' USING ERRCODE = 'P0002';
  END IF;
  IF p_add THEN
    UPDATE sms_contacts SET group_ids = group_ids || p_group, updated_at = now()
     WHERE tenant_id = p_tenant AND id = ANY (p_ids) AND NOT (p_group = ANY (group_ids));
  ELSE
    UPDATE sms_contacts SET group_ids = array_remove(group_ids, p_group), updated_at = now()
     WHERE tenant_id = p_tenant AND id = ANY (p_ids) AND p_group = ANY (group_ids);
  END IF;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- Delete a group. p_with_contacts also deletes contacts that were in this group and no other.
-- Returns contacts deleted, or -1 when the group isn't this tenant's.
CREATE OR REPLACE FUNCTION sms_group_delete(p_tenant uuid, p_group uuid, p_with_contacts boolean)
RETURNS int
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE n int := 0;
BEGIN
  DELETE FROM sms_contact_groups WHERE id = p_group AND tenant_id = p_tenant;
  IF NOT FOUND THEN
    RETURN -1;
  END IF;
  IF p_with_contacts THEN
    DELETE FROM sms_contacts WHERE tenant_id = p_tenant AND group_ids = ARRAY[p_group];
    GET DIAGNOSTICS n = ROW_COUNT;
  END IF;
  UPDATE sms_contacts SET group_ids = array_remove(group_ids, p_group), updated_at = now()
   WHERE tenant_id = p_tenant AND group_ids @> ARRAY[p_group];
  RETURN n;
END $$;

CREATE OR REPLACE FUNCTION sms_contact_group_counts(p_tenant uuid)
RETURNS TABLE (group_id uuid, contacts int)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public AS $$
  SELECT g.id, (SELECT count(*)::int FROM sms_contacts c
                 WHERE c.tenant_id = p_tenant AND c.group_ids @> ARRAY[g.id])
  FROM sms_contact_groups g WHERE g.tenant_id = p_tenant;
$$;

REVOKE EXECUTE ON FUNCTION sms_contacts_upsert(uuid, jsonb, uuid, text), sms_contacts_set_group(uuid, uuid, uuid[], boolean),
  sms_group_delete(uuid, uuid, boolean), sms_contact_group_counts(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION sms_contacts_upsert(uuid, jsonb, uuid, text), sms_contacts_set_group(uuid, uuid, uuid[], boolean),
  sms_group_delete(uuid, uuid, boolean), sms_contact_group_counts(uuid) TO service_role;
