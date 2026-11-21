-- 304: Stock places (shop, godowns, branches) and stock per place.
-- Plan: docs/plans/commerce-stock-plan.md ("The base").
--
-- * stock_places: a business's own named places. Every business gets "Shop" the first time
--   stock moves (or here, if it already has items), which bills take from by default.
-- * stock_levels: quantity per item / size-colour / place. catalog_items.stock_quantity and
--   catalog_item_variants.stock_quantity stay, always equal to the sum of their levels, so
--   every reader (AI, WhatsApp Forms, Meta catalogue sync, bills, reports) is unchanged.
-- * apply_stock_movement / apply_variant_stock_movement take an optional place (default:
--   the business's bill place) and keep the totals = sum of levels. stock_movements gets
--   place_id; reasons add 'transfer' (Move stock), 'count' (Stock count), 'write_off'.

CREATE TABLE IF NOT EXISTS stock_places (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 60),
  kind text NOT NULL DEFAULT 'shop' CHECK (kind IN ('shop', 'godown', 'other')),
  bills_from boolean NOT NULL DEFAULT false,     -- counter bills take stock from here
  online_from boolean NOT NULL DEFAULT false,    -- online / AI orders are packed from here
  archived boolean NOT NULL DEFAULT false,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_places_name_uq ON stock_places (tenant_id, lower(btrim(name))) WHERE NOT archived;
CREATE UNIQUE INDEX IF NOT EXISTS stock_places_bills_uq ON stock_places (tenant_id) WHERE bills_from AND NOT archived;
CREATE UNIQUE INDEX IF NOT EXISTS stock_places_online_uq ON stock_places (tenant_id) WHERE online_from AND NOT archived;
ALTER TABLE stock_places ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_places_tenant_member_select ON stock_places
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS stock_levels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  place_id uuid NOT NULL REFERENCES stock_places(id) ON DELETE RESTRICT,
  quantity integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_levels_uq
  ON stock_levels (catalog_item_id, (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)), place_id);
CREATE INDEX IF NOT EXISTS stock_levels_place_idx ON stock_levels (tenant_id, place_id);
CREATE INDEX IF NOT EXISTS stock_levels_variant_idx ON stock_levels (variant_id) WHERE variant_id IS NOT NULL;
ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_levels_tenant_member_select ON stock_levels
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS place_id uuid REFERENCES stock_places(id) ON DELETE SET NULL;
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_reason_check;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_reason_check
  CHECK (reason IN ('sale', 'restock', 'adjustment', 'return', 'transfer', 'count', 'write_off'));

-- The business's bill place, made ("Shop") the first time it is needed.
CREATE OR REPLACE FUNCTION default_stock_place(p_tenant_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_place uuid;
BEGIN
  SELECT id INTO v_place FROM stock_places
   WHERE tenant_id = p_tenant_id AND bills_from AND NOT archived LIMIT 1;
  IF v_place IS NOT NULL THEN
    RETURN v_place;
  END IF;
  SELECT id INTO v_place FROM stock_places
   WHERE tenant_id = p_tenant_id AND NOT archived ORDER BY sort_order, created_at LIMIT 1;
  IF v_place IS NOT NULL THEN
    RETURN v_place;
  END IF;
  INSERT INTO stock_places (tenant_id, name, kind, bills_from, online_from)
  VALUES (p_tenant_id, 'Shop', 'shop', true, true)
  ON CONFLICT DO NOTHING
  RETURNING id INTO v_place;
  IF v_place IS NULL THEN  -- made by a concurrent call
    SELECT id INTO v_place FROM stock_places
     WHERE tenant_id = p_tenant_id AND bills_from AND NOT archived LIMIT 1;
  END IF;
  RETURN v_place;
END $$;

-- Move one level (item, or item + size/colour, at a place). Returns the new quantity, or NULL
-- when it would go below zero (nothing changed). Callers keep the totals in step.
CREATE OR REPLACE FUNCTION _stock_level_add(
  p_tenant_id uuid, p_item_id uuid, p_variant_id uuid, p_place_id uuid, p_delta integer)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_after integer;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM stock_places WHERE id = p_place_id AND tenant_id = p_tenant_id) THEN
    RAISE EXCEPTION 'stock place % is not this business''s', p_place_id;
  END IF;
  IF p_delta > 0 THEN
    INSERT INTO stock_levels (tenant_id, catalog_item_id, variant_id, place_id, quantity)
    VALUES (p_tenant_id, p_item_id, p_variant_id, p_place_id, p_delta)
    ON CONFLICT (catalog_item_id, (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)), place_id)
    DO UPDATE SET quantity = stock_levels.quantity + EXCLUDED.quantity, updated_at = now()
    RETURNING quantity INTO v_after;
  ELSE
    UPDATE stock_levels SET quantity = quantity + p_delta, updated_at = now()
     WHERE catalog_item_id = p_item_id AND place_id = p_place_id AND tenant_id = p_tenant_id
       AND variant_id IS NOT DISTINCT FROM p_variant_id AND quantity + p_delta >= 0
    RETURNING quantity INTO v_after;
  END IF;
  RETURN v_after;
END $$;

DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid);
CREATE FUNCTION apply_stock_movement(
  p_tenant_id  uuid,
  p_item_id    uuid,
  p_delta      integer,
  p_reason     text,
  p_deal_id    uuid DEFAULT NULL,
  p_note       text DEFAULT NULL,
  p_created_by uuid DEFAULT NULL,
  p_place_id   uuid DEFAULT NULL
) RETURNS TABLE (ok boolean, tracked boolean, quantity_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_current integer;
  v_place   uuid;
  v_level   integer;
  v_after   integer;
BEGIN
  SELECT ci.stock_quantity INTO v_current FROM catalog_items ci
   WHERE ci.id = p_item_id AND ci.tenant_id = p_tenant_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT false, false, NULL::integer;
    RETURN;
  END IF;
  IF v_current IS NULL THEN
    RETURN QUERY SELECT true, false, NULL::integer;
    RETURN;
  END IF;
  v_place := COALESCE(p_place_id, default_stock_place(p_tenant_id));
  v_level := _stock_level_add(p_tenant_id, p_item_id, NULL, v_place, p_delta);
  IF v_level IS NULL THEN
    RETURN QUERY SELECT false, true, v_current;
    RETURN;
  END IF;
  UPDATE catalog_items
     SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l
                            WHERE l.catalog_item_id = p_item_id)
   WHERE id = p_item_id AND tenant_id = p_tenant_id
  RETURNING stock_quantity INTO v_after;
  INSERT INTO stock_movements (tenant_id, catalog_item_id, delta, quantity_after, reason, deal_id, note,
                               created_by, place_id)
  VALUES (p_tenant_id, p_item_id, p_delta, v_after, p_reason, p_deal_id, p_note, p_created_by, v_place);
  RETURN QUERY SELECT true, true, v_after;
END $$;
REVOKE EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid) TO service_role;

DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid);
CREATE FUNCTION apply_variant_stock_movement(
  p_tenant_id uuid, p_variant_id uuid, p_delta integer, p_reason text,
  p_deal_id uuid DEFAULT NULL, p_note text DEFAULT NULL, p_created_by uuid DEFAULT NULL,
  p_place_id uuid DEFAULT NULL)
RETURNS TABLE(ok boolean, quantity_after integer, item_quantity_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_item uuid;
  v_place uuid;
  v_level integer;
  v_after integer;
  v_item_after integer;
BEGIN
  SELECT v.catalog_item_id INTO v_item FROM catalog_item_variants v
   WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id;
  IF v_item IS NULL THEN
    RETURN QUERY SELECT false, NULL::integer, NULL::integer;
    RETURN;
  END IF;
  PERFORM 1 FROM catalog_items WHERE id = v_item AND tenant_id = p_tenant_id FOR UPDATE;
  v_place := COALESCE(p_place_id, default_stock_place(p_tenant_id));
  v_level := _stock_level_add(p_tenant_id, v_item, p_variant_id, v_place, p_delta);
  IF v_level IS NULL THEN
    RETURN QUERY SELECT false, (SELECT v.stock_quantity FROM catalog_item_variants v
                                 WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id), NULL::integer;
    RETURN;
  END IF;
  UPDATE catalog_item_variants
     SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l
                            WHERE l.variant_id = p_variant_id)
   WHERE id = p_variant_id AND tenant_id = p_tenant_id
  RETURNING stock_quantity INTO v_after;
  UPDATE catalog_items
     SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l
                            WHERE l.catalog_item_id = v_item)
   WHERE id = v_item AND tenant_id = p_tenant_id
  RETURNING stock_quantity INTO v_item_after;
  INSERT INTO stock_movements (tenant_id, catalog_item_id, variant_id, delta, quantity_after,
                               variant_quantity_after, reason, deal_id, note, created_by, place_id)
  VALUES (p_tenant_id, v_item, p_variant_id, p_delta, v_item_after, v_after, p_reason, p_deal_id, p_note,
          p_created_by, v_place);
  RETURN QUERY SELECT true, v_after, v_item_after;
END $$;
REVOKE EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid) TO service_role;
REVOKE EXECUTE ON FUNCTION default_stock_place(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION default_stock_place(uuid) TO service_role;
REVOKE EXECUTE ON FUNCTION _stock_level_add(uuid, uuid, uuid, uuid, integer) FROM PUBLIC, anon, authenticated;

-- Today's stock moves into each business's "Shop" (nothing looks different).
INSERT INTO stock_places (tenant_id, name, kind, bills_from, online_from)
SELECT DISTINCT ci.tenant_id, 'Shop', 'shop', true, true FROM catalog_items ci
 WHERE NOT EXISTS (SELECT 1 FROM stock_places p WHERE p.tenant_id = ci.tenant_id);
INSERT INTO stock_levels (tenant_id, catalog_item_id, variant_id, place_id, quantity)
SELECT v.tenant_id, v.catalog_item_id, v.id, default_stock_place(v.tenant_id), v.stock_quantity
  FROM catalog_item_variants v WHERE v.stock_quantity > 0
ON CONFLICT DO NOTHING;
INSERT INTO stock_levels (tenant_id, catalog_item_id, variant_id, place_id, quantity)
SELECT ci.tenant_id, ci.id, NULL, default_stock_place(ci.tenant_id), ci.stock_quantity
  FROM catalog_items ci
 WHERE ci.stock_quantity > 0
   AND NOT EXISTS (SELECT 1 FROM catalog_item_variants v WHERE v.catalog_item_id = ci.id)
ON CONFLICT DO NOTHING;
