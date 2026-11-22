-- 312: Stock count (plan: docs/plans/commerce-stock-plan.md, "The rest").
--
-- A count is for one place, in sections ("Saree rack 1"). Staff count by scanning or typing; each
-- counted line keeps what the system said AT THAT MOMENT (system_qty). Selling goes on: on Finish the
-- difference (counted − system_qty) is applied to the stock as it is then, so bills made during the
-- count are allowed for by themselves. Finish is owner only; every change is a stock movement with
-- reason 'count' and the reason given (Damaged / Lost / Count wrong / Found in shop).

CREATE TABLE IF NOT EXISTS stock_counts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  place_id uuid NOT NULL REFERENCES stock_places(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paused', 'finished', 'cancelled')),
  sections text[] NOT NULL DEFAULT '{}',
  started_by uuid,
  started_by_name text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_by uuid,
  finished_by_name text,
  finished_at timestamptz,
  loss_paise bigint NOT NULL DEFAULT 0,  -- at cost, set on Finish ("Stock loss")
  gain_paise bigint NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_counts_one_open_uq ON stock_counts (tenant_id, place_id)
  WHERE status IN ('open', 'paused');
CREATE INDEX IF NOT EXISTS stock_counts_tenant_idx ON stock_counts (tenant_id, started_at DESC);
ALTER TABLE stock_counts ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_counts_tenant_member_select ON stock_counts
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS stock_count_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  count_id uuid NOT NULL REFERENCES stock_counts(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  section text CHECK (section IS NULL OR length(section) <= 60),
  system_qty integer NOT NULL,
  counted_qty integer NOT NULL CHECK (counted_qty BETWEEN 0 AND 1000000),
  counted_by uuid,
  counted_by_name text,
  counted_at timestamptz NOT NULL DEFAULT now(),
  reason text CHECK (reason IS NULL OR reason IN ('damaged', 'lost', 'count_wrong', 'found', 'other')),
  applied_delta integer  -- what Finish changed (NULL until then)
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_count_lines_uq
  ON stock_count_lines (count_id, catalog_item_id, (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)));
ALTER TABLE stock_count_lines ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_count_lines_tenant_member_select ON stock_count_lines
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- Finish claims the count once (two owners tapping Finish can't apply it twice).
CREATE OR REPLACE FUNCTION claim_stock_count(p_tenant_id uuid, p_count uuid, p_user uuid, p_name text)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE stock_counts SET status = 'finished', finished_by = p_user, finished_by_name = p_name, finished_at = now()
   WHERE id = p_count AND tenant_id = p_tenant_id AND status IN ('open', 'paused');
  RETURN FOUND;
END $$;
REVOKE EXECUTE ON FUNCTION claim_stock_count(uuid, uuid, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_stock_count(uuid, uuid, uuid, text) TO service_role;
