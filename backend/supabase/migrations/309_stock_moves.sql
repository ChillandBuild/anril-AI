-- 309: Shop & godown (plan: docs/plans/commerce-stock-plan.md, part 4).
--
-- * stock_places.ready_note: what the AI tells a customer when an item is only at this place
--   ("ready in 1 day"). The business's own words; the AI says it in the customer's language.
-- * stock_moves / stock_move_lines: Move stock from one place to another. Sending takes the
--   stock out of the "from" place at once (it is on the way, sellable nowhere); it reaches the
--   "to" place only when someone there taps Received. A move is received or cancelled once.
-- * apply_stock_movement / apply_variant_stock_movement: with no place given and stock going
--   out (a sale, a correction), they start at p_first_place (default: the bill place) and take
--   the rest from the other places, so a shop that is out but has it in the godown can still
--   sell it. A given place (p_place_id) is used exactly, as before.

ALTER TABLE stock_places ADD COLUMN IF NOT EXISTS ready_note text
  CHECK (ready_note IS NULL OR length(ready_note) <= 80);

CREATE TABLE IF NOT EXISTS stock_moves (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  from_place_id uuid NOT NULL REFERENCES stock_places(id) ON DELETE RESTRICT,
  to_place_id uuid NOT NULL REFERENCES stock_places(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'on_the_way' CHECK (status IN ('on_the_way', 'received', 'cancelled')),
  note text CHECK (note IS NULL OR length(note) <= 300),
  sent_by uuid,
  sent_by_name text,
  done_by uuid,
  done_by_name text,
  created_at timestamptz NOT NULL DEFAULT now(),
  done_at timestamptz,
  CHECK (from_place_id <> to_place_id)
);
CREATE INDEX IF NOT EXISTS stock_moves_tenant_idx ON stock_moves (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS stock_moves_open_idx ON stock_moves (tenant_id) WHERE status = 'on_the_way';
ALTER TABLE stock_moves ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS stock_moves_tenant_member_select ON stock_moves;
CREATE POLICY stock_moves_tenant_member_select ON stock_moves
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS stock_move_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  move_id uuid NOT NULL REFERENCES stock_moves(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 100000)
);
CREATE INDEX IF NOT EXISTS stock_move_lines_move_idx ON stock_move_lines (move_id);
ALTER TABLE stock_move_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS stock_move_lines_tenant_member_select ON stock_move_lines;
CREATE POLICY stock_move_lines_tenant_member_select ON stock_move_lines
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- ── stock functions: same as 304, plus "start here, then the other places" ─────────────────

DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid);
CREATE FUNCTION apply_stock_movement(
  p_tenant_id   uuid,
  p_item_id     uuid,
  p_delta       integer,
  p_reason      text,
  p_deal_id     uuid DEFAULT NULL,
  p_note        text DEFAULT NULL,
  p_created_by  uuid DEFAULT NULL,
  p_place_id    uuid DEFAULT NULL,
  p_first_place uuid DEFAULT NULL
) RETURNS TABLE (ok boolean, tracked boolean, quantity_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_current integer;
  v_place   uuid;
  v_level   integer;
  v_after   integer;
  v_left    integer;
  v_take    integer;
  r         record;
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
  IF p_place_id IS NULL AND p_first_place IS NOT NULL THEN
    SELECT id INTO v_place FROM stock_places
     WHERE id = p_first_place AND tenant_id = p_tenant_id AND NOT archived;
  END IF;
  v_place := COALESCE(p_place_id, v_place, default_stock_place(p_tenant_id));

  IF p_place_id IS NULL AND p_delta < 0 THEN
    -- Start at v_place, then the other places (their order), until the quantity is found.
    IF (SELECT COALESCE(sum(l.quantity), 0) FROM stock_levels l
         WHERE l.catalog_item_id = p_item_id AND l.variant_id IS NULL) < -p_delta THEN
      RETURN QUERY SELECT false, true, v_current;
      RETURN;
    END IF;
    v_left := -p_delta;
    FOR r IN
      SELECT l.place_id, l.quantity FROM stock_levels l JOIN stock_places p ON p.id = l.place_id
       WHERE l.catalog_item_id = p_item_id AND l.variant_id IS NULL AND l.quantity > 0
       ORDER BY (l.place_id = v_place) DESC, p.sort_order, p.created_at
    LOOP
      v_take := least(r.quantity, v_left);
      PERFORM _stock_level_add(p_tenant_id, p_item_id, NULL, r.place_id, -v_take);
      UPDATE catalog_items
         SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l
                                WHERE l.catalog_item_id = p_item_id)
       WHERE id = p_item_id AND tenant_id = p_tenant_id
      RETURNING stock_quantity INTO v_after;
      INSERT INTO stock_movements (tenant_id, catalog_item_id, delta, quantity_after, reason, deal_id, note,
                                   created_by, place_id)
      VALUES (p_tenant_id, p_item_id, -v_take, v_after, p_reason, p_deal_id, p_note, p_created_by, r.place_id);
      v_left := v_left - v_take;
      EXIT WHEN v_left = 0;
    END LOOP;
    RETURN QUERY SELECT true, true, v_after;
    RETURN;
  END IF;

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
REVOKE EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid) TO service_role;

DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid);
CREATE FUNCTION apply_variant_stock_movement(
  p_tenant_id uuid, p_variant_id uuid, p_delta integer, p_reason text,
  p_deal_id uuid DEFAULT NULL, p_note text DEFAULT NULL, p_created_by uuid DEFAULT NULL,
  p_place_id uuid DEFAULT NULL, p_first_place uuid DEFAULT NULL)
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
  v_left integer;
  v_take integer;
  r record;
BEGIN
  SELECT v.catalog_item_id INTO v_item FROM catalog_item_variants v
   WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id;
  IF v_item IS NULL THEN
    RETURN QUERY SELECT false, NULL::integer, NULL::integer;
    RETURN;
  END IF;
  PERFORM 1 FROM catalog_items WHERE id = v_item AND tenant_id = p_tenant_id FOR UPDATE;
  IF p_place_id IS NULL AND p_first_place IS NOT NULL THEN
    SELECT id INTO v_place FROM stock_places
     WHERE id = p_first_place AND tenant_id = p_tenant_id AND NOT archived;
  END IF;
  v_place := COALESCE(p_place_id, v_place, default_stock_place(p_tenant_id));

  IF p_place_id IS NULL AND p_delta < 0 THEN
    IF (SELECT COALESCE(sum(l.quantity), 0) FROM stock_levels l WHERE l.variant_id = p_variant_id) < -p_delta THEN
      RETURN QUERY SELECT false, (SELECT v.stock_quantity FROM catalog_item_variants v
                                   WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id), NULL::integer;
      RETURN;
    END IF;
    v_left := -p_delta;
    FOR r IN
      SELECT l.place_id, l.quantity FROM stock_levels l JOIN stock_places p ON p.id = l.place_id
       WHERE l.variant_id = p_variant_id AND l.quantity > 0
       ORDER BY (l.place_id = v_place) DESC, p.sort_order, p.created_at
    LOOP
      v_take := least(r.quantity, v_left);
      PERFORM _stock_level_add(p_tenant_id, v_item, p_variant_id, r.place_id, -v_take);
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
      VALUES (p_tenant_id, v_item, p_variant_id, -v_take, v_item_after, v_after, p_reason, p_deal_id, p_note,
              p_created_by, r.place_id);
      v_left := v_left - v_take;
      EXIT WHEN v_left = 0;
    END LOOP;
    RETURN QUERY SELECT true, v_after, v_item_after;
    RETURN;
  END IF;

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
REVOKE EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid) TO service_role;

-- ── Move stock ──────────────────────────────────────────────────────────────────────────────

-- One line of a move, in or out of a place. Raises (undoing the whole move) when it can't.
CREATE OR REPLACE FUNCTION _stock_move_line(
  p_tenant_id uuid, p_item uuid, p_variant uuid, p_place uuid, p_delta integer, p_note text, p_user uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  r record;
BEGIN
  IF p_variant IS NOT NULL THEN
    SELECT * INTO r FROM apply_variant_stock_movement(p_tenant_id, p_variant, p_delta, 'transfer', NULL, p_note,
                                                      p_user, p_place);
    IF NOT r.ok THEN
      RAISE EXCEPTION 'stock_move_short:%', p_variant USING ERRCODE = 'P0001';
    END IF;
  ELSE
    SELECT * INTO r FROM apply_stock_movement(p_tenant_id, p_item, p_delta, 'transfer', NULL, p_note, p_user, p_place);
    IF NOT r.ok OR NOT r.tracked THEN
      RAISE EXCEPTION 'stock_move_short:%', p_item USING ERRCODE = 'P0001';
    END IF;
  END IF;
END $$;

-- Send: stock leaves p_from now. Lines: [{"item": uuid, "variant": uuid|null, "qty": int}].
CREATE OR REPLACE FUNCTION send_stock_move(
  p_tenant_id uuid, p_from uuid, p_to uuid, p_lines jsonb, p_note text, p_user uuid, p_user_name text)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_move uuid;
  v_to_name text;
  li jsonb;
BEGIN
  IF p_from = p_to THEN
    RAISE EXCEPTION 'stock_move_same_place' USING ERRCODE = 'P0001';
  END IF;
  IF (SELECT count(*) FROM stock_places WHERE id IN (p_from, p_to) AND tenant_id = p_tenant_id AND NOT archived) <> 2 THEN
    RAISE EXCEPTION 'stock_move_bad_place' USING ERRCODE = 'P0001';
  END IF;
  SELECT name INTO v_to_name FROM stock_places WHERE id = p_to;
  INSERT INTO stock_moves (tenant_id, from_place_id, to_place_id, note, sent_by, sent_by_name)
  VALUES (p_tenant_id, p_from, p_to, p_note, p_user, p_user_name)
  RETURNING id INTO v_move;
  FOR li IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
    INSERT INTO stock_move_lines (tenant_id, move_id, catalog_item_id, variant_id, quantity)
    VALUES (p_tenant_id, v_move, (li->>'item')::uuid, NULLIF(li->>'variant', '')::uuid, (li->>'qty')::integer);
    PERFORM _stock_move_line(p_tenant_id, (li->>'item')::uuid, NULLIF(li->>'variant', '')::uuid, p_from,
                             -(li->>'qty')::integer, 'On the way to ' || v_to_name, p_user);
  END LOOP;
  RETURN v_move;
END $$;

-- Received (stock lands in "to") or cancelled (stock goes back to "from"). Once only: false
-- when the move isn't on the way any more.
CREATE OR REPLACE FUNCTION finish_stock_move(
  p_tenant_id uuid, p_move uuid, p_received boolean, p_user uuid, p_user_name text)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_place uuid;
  v_other_place uuid;
  v_other text;
  l record;
BEGIN
  UPDATE stock_moves
     SET status = CASE WHEN p_received THEN 'received' ELSE 'cancelled' END,
         done_by = p_user, done_by_name = p_user_name, done_at = now()
   WHERE id = p_move AND tenant_id = p_tenant_id AND status = 'on_the_way'
  RETURNING CASE WHEN p_received THEN to_place_id ELSE from_place_id END,
            CASE WHEN p_received THEN from_place_id ELSE to_place_id END
       INTO v_place, v_other_place;
  IF v_place IS NULL THEN
    RETURN false;
  END IF;
  SELECT name INTO v_other FROM stock_places WHERE id = v_other_place;
  FOR l IN SELECT catalog_item_id, variant_id, quantity FROM stock_move_lines WHERE move_id = p_move LOOP
    PERFORM _stock_move_line(p_tenant_id, l.catalog_item_id, l.variant_id, v_place, l.quantity,
                             CASE WHEN p_received THEN 'Received from ' || v_other
                                  ELSE 'Move to ' || v_other || ' cancelled' END, p_user);
  END LOOP;
  RETURN true;
END $$;

REVOKE EXECUTE ON FUNCTION _stock_move_line(uuid, uuid, uuid, uuid, integer, text, uuid) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION send_stock_move(uuid, uuid, uuid, jsonb, text, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION send_stock_move(uuid, uuid, uuid, jsonb, text, uuid, text) TO service_role;
REVOKE EXECUTE ON FUNCTION finish_stock_move(uuid, uuid, boolean, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION finish_stock_move(uuid, uuid, boolean, uuid, text) TO service_role;
