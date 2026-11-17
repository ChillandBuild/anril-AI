-- 278_customer_groups.sql
-- Customers › Groups: named lists of leads ("Wedding enquiries") that broadcasts and
-- calling can target later.
--
-- - customer_groups: one row per group. kind = 'picked' (people added by hand from
--   Customers › All people › Add to group) or 'rule' (fills itself from `rule`, a saved
--   filter; NOT built yet; the column is here so rule groups need no new table).
--   A 'picked' group never has a rule; a 'rule' group always has one.
-- - customer_group_members: who is in a picked group. One row per (group, lead).
--   Said-stop (opted_out) people stay listed but are left out when a group is used to send.
--
-- RLS on with no policies: service role only, like 240/248. Routes gate by tenant_id.

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS customer_groups (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  kind        text NOT NULL DEFAULT 'picked' CHECK (kind IN ('picked', 'rule')),
  rule        jsonb,
  created_by  uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'rule') = (rule IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS customer_groups_name_uq ON customer_groups (tenant_id, lower(btrim(name)));

CREATE TABLE IF NOT EXISTS customer_group_members (
  group_id   uuid NOT NULL REFERENCES customer_groups(id) ON DELETE CASCADE,
  lead_id    uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  added_by   uuid,
  added_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, lead_id)
);
CREATE INDEX IF NOT EXISTS customer_group_members_lead_idx ON customer_group_members (lead_id);
CREATE INDEX IF NOT EXISTS customer_group_members_tenant_idx ON customer_group_members (tenant_id);

ALTER TABLE customer_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_group_members ENABLE ROW LEVEL SECURITY;
