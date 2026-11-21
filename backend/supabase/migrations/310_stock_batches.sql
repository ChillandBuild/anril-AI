-- 310: Batches & expiry (plan: docs/plans/commerce-stock-plan.md, "Part 5 in detail").
--
-- * catalog_items.tracks_batches: switched on per item. Turning it on puts the item's stock at each
--   place into one batch "Opening stock" (no expiry), so for a batch item the stock at a place is
--   always the sum of its active batches there.
-- * stock_batches: one row per batch per place (batch no., expiry, quantity, cost, supplier,
--   discount %, sell first). A batch with no number is batch_no '' ("No batch no.").
-- * Every stock change still goes through apply_stock_movement / apply_variant_stock_movement, now
--   thin wrappers over _stock_change, which also handles batches:
--     - a given batch (p_batch_id) is used exactly; a sale never takes an expired batch;
--     - stock out with no batch: Sell-first batches, then earliest expiry, bill (or first) place first,
--       then the other places; a sale skips expired batches;
--     - stock in with no batch: into p_new_batch ({batch_no, expiry, cost_paise, supplier_id,
--       stock_in_line_id}) or the place's "No batch no." batch.
-- * deal_item_batches: which batches a bill line took (printed on the bill; a return goes back there).
-- * stock_move_lines.batches: the batches a move took, so Received recreates them at the other place.
-- * supplier_returns: Return to supplier lowers what the business owes that supplier.

ALTER TABLE catalog_items ADD COLUMN IF NOT EXISTS tracks_batches boolean NOT NULL DEFAULT false;
ALTER TABLE deal_items ADD COLUMN IF NOT EXISTS batch_id uuid;  -- the batch staff chose (else first-expiring)
ALTER TABLE stock_move_lines ADD COLUMN IF NOT EXISTS batches jsonb;

CREATE TABLE IF NOT EXISTS stock_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  place_id uuid NOT NULL REFERENCES stock_places(id) ON DELETE RESTRICT,
  batch_no text NOT NULL DEFAULT '' CHECK (length(batch_no) <= 40),
  expiry_date date,
  quantity integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  cost_paise bigint CHECK (cost_paise IS NULL OR cost_paise >= 0),
  supplier_id uuid REFERENCES suppliers(id) ON DELETE SET NULL,
  stock_in_line_id uuid REFERENCES stock_in_lines(id) ON DELETE SET NULL,
  discount_pct integer NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 90),
  sell_first boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'returned', 'written_off', 'closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_batches_uq ON stock_batches (
  catalog_item_id, (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)), place_id, batch_no,
  (COALESCE(expiry_date, 'infinity'::date)), (COALESCE(supplier_id, '00000000-0000-0000-0000-000000000000'::uuid)))
  WHERE status = 'active';
CREATE INDEX IF NOT EXISTS stock_batches_tenant_idx ON stock_batches (tenant_id, expiry_date) WHERE status = 'active';
ALTER TABLE stock_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_batches_tenant_member_select ON stock_batches
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS deal_item_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  deal_id uuid REFERENCES deals(id) ON DELETE CASCADE,
  deal_item_id uuid NOT NULL REFERENCES deal_items(id) ON DELETE CASCADE,
  batch_id uuid NOT NULL REFERENCES stock_batches(id) ON DELETE CASCADE,
  quantity integer NOT NULL,  -- taken (positive); a return adds a negative row
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS deal_item_batches_item_idx ON deal_item_batches (deal_item_id);
ALTER TABLE deal_item_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY deal_item_batches_tenant_member_select ON deal_item_batches
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

CREATE TABLE IF NOT EXISTS supplier_returns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  supplier_id uuid NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  batch_id uuid REFERENCES stock_batches(id) ON DELETE SET NULL,
  catalog_item_id uuid REFERENCES catalog_items(id) ON DELETE SET NULL,
  quantity integer NOT NULL CHECK (quantity > 0),
  amount_paise bigint NOT NULL DEFAULT 0 CHECK (amount_paise >= 0),
  note text CHECK (note IS NULL OR length(note) <= 300),
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS supplier_returns_supplier_idx ON supplier_returns (tenant_id, supplier_id);
ALTER TABLE supplier_returns ENABLE ROW LEVEL SECURITY;
CREATE POLICY supplier_returns_tenant_member_select ON supplier_returns
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS batch_id uuid REFERENCES stock_batches(id) ON DELETE SET NULL;
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_reason_check;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_reason_check
  CHECK (reason IN ('sale', 'restock', 'adjustment', 'return', 'transfer', 'count', 'write_off', 'supplier_return'));

-- ── the one place stock changes ──────────────────────────────────────────────────────────────

-- One piece at one place (and batch): level, batch, totals, movement row, bill-line pick.
CREATE OR REPLACE FUNCTION _stock_piece(
  p_tenant uuid, p_item uuid, p_variant uuid, p_place uuid, p_batch uuid, p_delta integer, p_reason text,
  p_deal uuid, p_note text, p_user uuid, p_deal_item uuid)
RETURNS TABLE (line_after integer, item_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_line integer;
  v_item integer;
BEGIN
  IF _stock_level_add(p_tenant, p_item, p_variant, p_place, p_delta) IS NULL THEN
    RAISE EXCEPTION 'stock_level_short' USING ERRCODE = 'P0001';  -- callers check first; never half-done
  END IF;
  IF p_batch IS NOT NULL THEN
    UPDATE stock_batches SET quantity = quantity + p_delta WHERE id = p_batch AND quantity + p_delta >= 0;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'stock_batch_short' USING ERRCODE = 'P0001';
    END IF;
    IF to_regclass('pg_temp._stock_taken') IS NOT NULL AND p_delta < 0 THEN
      EXECUTE 'INSERT INTO pg_temp._stock_taken (batch_id, qty) VALUES ($1, $2)' USING p_batch, -p_delta;
    END IF;
    IF p_deal_item IS NOT NULL THEN
      INSERT INTO deal_item_batches (tenant_id, deal_id, deal_item_id, batch_id, quantity)
      VALUES (p_tenant, p_deal, p_deal_item, p_batch, -p_delta);
    END IF;
  END IF;
  IF p_variant IS NOT NULL THEN
    UPDATE catalog_item_variants
       SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l WHERE l.variant_id = p_variant)
     WHERE id = p_variant AND tenant_id = p_tenant
    RETURNING stock_quantity INTO v_line;
  END IF;
  UPDATE catalog_items
     SET stock_quantity = (SELECT COALESCE(sum(l.quantity), 0)::integer FROM stock_levels l WHERE l.catalog_item_id = p_item)
   WHERE id = p_item AND tenant_id = p_tenant
  RETURNING stock_quantity INTO v_item;
  INSERT INTO stock_movements (tenant_id, catalog_item_id, variant_id, delta, quantity_after, variant_quantity_after,
                               reason, deal_id, note, created_by, place_id, batch_id)
  VALUES (p_tenant, p_item, p_variant, p_delta, v_item, v_line, p_reason, p_deal, p_note, p_user, p_place, p_batch);
  RETURN QUERY SELECT COALESCE(v_line, v_item), v_item;
END $$;

-- Every stock change. The caller has locked the catalog_items row. ok=false = nothing changed.
CREATE OR REPLACE FUNCTION _stock_change(
  p_tenant uuid, p_item uuid, p_variant uuid, p_delta integer, p_reason text, p_deal uuid, p_note text,
  p_user uuid, p_place uuid, p_first_place uuid, p_batch uuid, p_deal_item uuid, p_new_batch jsonb)
RETURNS TABLE (ok boolean, line_after integer, item_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_batches boolean;
  v_place uuid;
  v_today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
  v_left integer;
  v_take integer;
  v_line integer;
  v_item integer;
  v_no text;
  v_exp date;
  v_sup uuid;
  v_cost bigint;
  b record;
  r record;
BEGIN
  SELECT tracks_batches INTO v_batches FROM catalog_items WHERE id = p_item AND tenant_id = p_tenant;
  IF COALESCE(p_delta, 0) = 0 THEN  -- nothing to change (309 behaviour: not an error)
    RETURN QUERY SELECT false, NULL::integer, NULL::integer;
    RETURN;
  END IF;
  IF p_place IS NULL AND p_first_place IS NOT NULL THEN
    SELECT id INTO v_place FROM stock_places WHERE id = p_first_place AND tenant_id = p_tenant AND NOT archived;
  END IF;
  v_place := COALESCE(p_place, v_place, default_stock_place(p_tenant));

  -- 1. A named batch (a bill line's batch, a return to the same batch, write-off, supplier return).
  IF p_batch IS NOT NULL THEN
    SELECT * INTO b FROM stock_batches
     WHERE id = p_batch AND tenant_id = p_tenant AND catalog_item_id = p_item
       AND variant_id IS NOT DISTINCT FROM p_variant AND status = 'active' FOR UPDATE;
    IF NOT FOUND OR (p_place IS NOT NULL AND b.place_id <> p_place) OR b.quantity + p_delta < 0
       OR (p_delta < 0 AND p_reason = 'sale' AND b.expiry_date < v_today) THEN
      RETURN QUERY SELECT false, NULL::integer, NULL::integer;
      RETURN;
    END IF;
    SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, b.place_id, b.id, p_delta, p_reason, p_deal, p_note,
                                      p_user, p_deal_item);
    RETURN QUERY SELECT true, r.line_after, r.item_after;
    RETURN;
  END IF;

  -- 2. Stock in: into the given batch details, or the place's "No batch no." batch.
  IF p_delta > 0 THEN
    IF v_batches THEN
      v_no := left(btrim(COALESCE(p_new_batch->>'batch_no', '')), 40);
      v_exp := NULLIF(p_new_batch->>'expiry', '')::date;
      v_sup := NULLIF(p_new_batch->>'supplier_id', '')::uuid;
      v_cost := NULLIF(p_new_batch->>'cost_paise', '')::bigint;
      -- the same batch from the same supplier tops up (latest cost wins); another supplier is its own batch
      SELECT * INTO b FROM stock_batches
       WHERE catalog_item_id = p_item AND variant_id IS NOT DISTINCT FROM p_variant AND place_id = v_place
         AND batch_no = v_no AND expiry_date IS NOT DISTINCT FROM v_exp AND supplier_id IS NOT DISTINCT FROM v_sup
         AND status = 'active' FOR UPDATE;
      IF NOT FOUND THEN
        INSERT INTO stock_batches (tenant_id, catalog_item_id, variant_id, place_id, batch_no, expiry_date, cost_paise,
                                   supplier_id, stock_in_line_id)
        VALUES (p_tenant, p_item, p_variant, v_place, v_no, v_exp, v_cost, v_sup,
                NULLIF(p_new_batch->>'stock_in_line_id', '')::uuid)
        RETURNING * INTO b;
      ELSIF v_cost IS NOT NULL THEN
        UPDATE stock_batches SET cost_paise = v_cost,
               stock_in_line_id = COALESCE(NULLIF(p_new_batch->>'stock_in_line_id', '')::uuid, stock_in_line_id)
         WHERE id = b.id;
      END IF;
      SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, v_place, b.id, p_delta, p_reason, p_deal, p_note,
                                        p_user, p_deal_item);
    ELSE
      SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, v_place, NULL, p_delta, p_reason, p_deal, p_note,
                                        p_user, p_deal_item);
    END IF;
    RETURN QUERY SELECT true, r.line_after, r.item_after;
    RETURN;
  END IF;

  -- 3. Stock out, batch item: Sell first, then earliest expiry; this place first, then the others
  --    (only this place when one was given). A sale never takes an expired batch.
  IF v_batches THEN
    IF (SELECT COALESCE(sum(sb.quantity), 0) FROM stock_batches sb
         WHERE sb.catalog_item_id = p_item AND sb.variant_id IS NOT DISTINCT FROM p_variant AND sb.status = 'active'
           AND (p_place IS NULL OR sb.place_id = p_place)
           AND (p_reason <> 'sale' OR sb.expiry_date IS NULL OR sb.expiry_date >= v_today)) < -p_delta THEN
      RETURN QUERY SELECT false, NULL::integer, NULL::integer;
      RETURN;
    END IF;
    v_left := -p_delta;
    FOR b IN
      SELECT sb.id, sb.place_id, sb.quantity FROM stock_batches sb JOIN stock_places p ON p.id = sb.place_id
       WHERE sb.catalog_item_id = p_item AND sb.variant_id IS NOT DISTINCT FROM p_variant AND sb.status = 'active'
         AND sb.quantity > 0 AND (p_place IS NULL OR sb.place_id = p_place)
         AND (p_reason <> 'sale' OR sb.expiry_date IS NULL OR sb.expiry_date >= v_today)
       ORDER BY (sb.place_id = v_place) DESC, p.sort_order, p.created_at, sb.sell_first DESC,
                sb.expiry_date ASC NULLS LAST, sb.created_at
       FOR UPDATE OF sb
    LOOP
      v_take := least(b.quantity, v_left);
      SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, b.place_id, b.id, -v_take, p_reason, p_deal,
                                        p_note, p_user, p_deal_item);
      v_left := v_left - v_take;
      EXIT WHEN v_left = 0;
    END LOOP;
    RETURN QUERY SELECT true, r.line_after, r.item_after;
    RETURN;
  END IF;

  -- 4. Stock out, no batches: the given place exactly, or this place first then the others (309).
  IF p_place IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM stock_levels l WHERE l.catalog_item_id = p_item
                     AND l.variant_id IS NOT DISTINCT FROM p_variant AND l.place_id = p_place
                     AND l.quantity >= -p_delta) THEN
      RETURN QUERY SELECT false, NULL::integer, NULL::integer;
      RETURN;
    END IF;
    SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, p_place, NULL, p_delta, p_reason, p_deal, p_note,
                                      p_user, p_deal_item);
    RETURN QUERY SELECT true, r.line_after, r.item_after;
    RETURN;
  END IF;
  IF (SELECT COALESCE(sum(l.quantity), 0) FROM stock_levels l
       WHERE l.catalog_item_id = p_item AND l.variant_id IS NOT DISTINCT FROM p_variant) < -p_delta THEN
    RETURN QUERY SELECT false, NULL::integer, NULL::integer;
    RETURN;
  END IF;
  v_left := -p_delta;
  FOR b IN
    SELECT l.place_id, l.quantity FROM stock_levels l JOIN stock_places p ON p.id = l.place_id
     WHERE l.catalog_item_id = p_item AND l.variant_id IS NOT DISTINCT FROM p_variant AND l.quantity > 0
     ORDER BY (l.place_id = v_place) DESC, p.sort_order, p.created_at
  LOOP
    v_take := least(b.quantity, v_left);
    SELECT * INTO r FROM _stock_piece(p_tenant, p_item, p_variant, b.place_id, NULL, -v_take, p_reason, p_deal, p_note,
                                      p_user, p_deal_item);
    v_left := v_left - v_take;
    EXIT WHEN v_left = 0;
  END LOOP;
  RETURN QUERY SELECT true, r.line_after, r.item_after;
END $$;

DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid);
CREATE FUNCTION apply_stock_movement(
  p_tenant_id uuid, p_item_id uuid, p_delta integer, p_reason text, p_deal_id uuid DEFAULT NULL,
  p_note text DEFAULT NULL, p_created_by uuid DEFAULT NULL, p_place_id uuid DEFAULT NULL,
  p_first_place uuid DEFAULT NULL, p_batch_id uuid DEFAULT NULL, p_deal_item_id uuid DEFAULT NULL,
  p_new_batch jsonb DEFAULT NULL
) RETURNS TABLE (ok boolean, tracked boolean, quantity_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_current integer;
  r record;
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
  SELECT * INTO r FROM _stock_change(p_tenant_id, p_item_id, NULL, p_delta, p_reason, p_deal_id, p_note, p_created_by,
                                     p_place_id, p_first_place, p_batch_id, p_deal_item_id, p_new_batch);
  RETURN QUERY SELECT r.ok, true, CASE WHEN r.ok THEN r.item_after ELSE v_current END;
END $$;

DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid);
CREATE FUNCTION apply_variant_stock_movement(
  p_tenant_id uuid, p_variant_id uuid, p_delta integer, p_reason text, p_deal_id uuid DEFAULT NULL,
  p_note text DEFAULT NULL, p_created_by uuid DEFAULT NULL, p_place_id uuid DEFAULT NULL,
  p_first_place uuid DEFAULT NULL, p_batch_id uuid DEFAULT NULL, p_deal_item_id uuid DEFAULT NULL,
  p_new_batch jsonb DEFAULT NULL
) RETURNS TABLE (ok boolean, quantity_after integer, item_quantity_after integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_item uuid;
  r record;
BEGIN
  SELECT v.catalog_item_id INTO v_item FROM catalog_item_variants v
   WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id;
  IF v_item IS NULL THEN
    RETURN QUERY SELECT false, NULL::integer, NULL::integer;
    RETURN;
  END IF;
  PERFORM 1 FROM catalog_items WHERE id = v_item AND tenant_id = p_tenant_id FOR UPDATE;
  SELECT * INTO r FROM _stock_change(p_tenant_id, v_item, p_variant_id, p_delta, p_reason, p_deal_id, p_note,
                                     p_created_by, p_place_id, p_first_place, p_batch_id, p_deal_item_id, p_new_batch);
  IF NOT r.ok THEN
    RETURN QUERY SELECT false, (SELECT v.stock_quantity FROM catalog_item_variants v
                                 WHERE v.id = p_variant_id AND v.tenant_id = p_tenant_id), NULL::integer;
    RETURN;
  END IF;
  RETURN QUERY SELECT true, r.line_after, r.item_after;
END $$;

-- ── moves keep their batches ─────────────────────────────────────────────────────────────────

DROP FUNCTION IF EXISTS _stock_move_line(uuid, uuid, uuid, uuid, integer, text, uuid);
CREATE FUNCTION _stock_move_line(
  p_tenant_id uuid, p_item uuid, p_variant uuid, p_place uuid, p_delta integer, p_note text, p_user uuid,
  p_batch uuid DEFAULT NULL, p_new_batch jsonb DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  r record;
BEGIN
  PERFORM 1 FROM catalog_items WHERE id = p_item AND tenant_id = p_tenant_id
     AND (p_variant IS NOT NULL OR stock_quantity IS NOT NULL) FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'stock_move_short:%', COALESCE(p_variant, p_item) USING ERRCODE = 'P0001';
  END IF;
  SELECT * INTO r FROM _stock_change(p_tenant_id, p_item, p_variant, p_delta, 'transfer', NULL, p_note, p_user,
                                     p_place, NULL, p_batch, NULL, p_new_batch);
  IF NOT r.ok THEN
    RAISE EXCEPTION 'stock_move_short:%', COALESCE(p_variant, p_item) USING ERRCODE = 'P0001';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION send_stock_move(
  p_tenant_id uuid, p_from uuid, p_to uuid, p_lines jsonb, p_note text, p_user uuid, p_user_name text)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_move uuid;
  v_line uuid;
  v_to_name text;
  li jsonb;
BEGIN
  IF p_from = p_to THEN
    RAISE EXCEPTION 'stock_move_same_place' USING ERRCODE = 'P0001';
  END IF;
  IF (SELECT count(*) FROM stock_places WHERE id IN (p_from, p_to) AND tenant_id = p_tenant_id AND NOT archived) <> 2 THEN
    RAISE EXCEPTION 'stock_move_bad_place' USING ERRCODE = 'P0001';
  END IF;
  CREATE TEMP TABLE IF NOT EXISTS _stock_taken (batch_id uuid, qty integer) ON COMMIT DROP;
  SELECT name INTO v_to_name FROM stock_places WHERE id = p_to;
  INSERT INTO stock_moves (tenant_id, from_place_id, to_place_id, note, sent_by, sent_by_name)
  VALUES (p_tenant_id, p_from, p_to, p_note, p_user, p_user_name)
  RETURNING id INTO v_move;
  FOR li IN SELECT * FROM jsonb_array_elements(p_lines) LOOP
    DELETE FROM _stock_taken;
    INSERT INTO stock_move_lines (tenant_id, move_id, catalog_item_id, variant_id, quantity)
    VALUES (p_tenant_id, v_move, (li->>'item')::uuid, NULLIF(li->>'variant', '')::uuid, (li->>'qty')::integer)
    RETURNING id INTO v_line;
    PERFORM _stock_move_line(p_tenant_id, (li->>'item')::uuid, NULLIF(li->>'variant', '')::uuid, p_from,
                             -(li->>'qty')::integer, 'On the way to ' || v_to_name, p_user);
    UPDATE stock_move_lines SET batches = (
      SELECT jsonb_agg(jsonb_build_object('batch_id', t.batch_id, 'qty', t.qty, 'batch_no', sb.batch_no,
                                          'expiry', sb.expiry_date, 'cost_paise', sb.cost_paise,
                                          'supplier_id', sb.supplier_id))
        FROM _stock_taken t JOIN stock_batches sb ON sb.id = t.batch_id)
     WHERE id = v_line;
  END LOOP;
  DROP TABLE IF EXISTS _stock_taken;
  RETURN v_move;
END $$;

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
  v_note text;
  l record;
  bt jsonb;
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
  v_note := CASE WHEN p_received THEN 'Received from ' || v_other ELSE 'Move to ' || v_other || ' cancelled' END;
  FOR l IN SELECT catalog_item_id, variant_id, quantity, batches FROM stock_move_lines WHERE move_id = p_move LOOP
    IF l.batches IS NULL OR jsonb_array_length(l.batches) = 0 THEN
      PERFORM _stock_move_line(p_tenant_id, l.catalog_item_id, l.variant_id, v_place, l.quantity, v_note, p_user);
    ELSE
      FOR bt IN SELECT * FROM jsonb_array_elements(l.batches) LOOP
        IF p_received THEN  -- the same batch (no., expiry, cost, supplier) at the other place
          PERFORM _stock_move_line(p_tenant_id, l.catalog_item_id, l.variant_id, v_place, (bt->>'qty')::integer,
                                   v_note, p_user, NULL, bt);
        ELSIF EXISTS (SELECT 1 FROM stock_batches WHERE id = (bt->>'batch_id')::uuid AND status = 'active') THEN
          -- back into the very batch it left
          PERFORM _stock_move_line(p_tenant_id, l.catalog_item_id, l.variant_id, v_place, (bt->>'qty')::integer,
                                   v_note, p_user, (bt->>'batch_id')::uuid);
        ELSE                -- that batch was returned / removed meanwhile: the same details, as a batch again
          PERFORM _stock_move_line(p_tenant_id, l.catalog_item_id, l.variant_id, v_place, (bt->>'qty')::integer,
                                   v_note, p_user, NULL, bt);
        END IF;
      END LOOP;
    END IF;
  END LOOP;
  RETURN true;
END $$;

-- ── switching batches on / off, returning a batch to its supplier ───────────────────────────

CREATE OR REPLACE FUNCTION set_batch_tracking(p_tenant_id uuid, p_item uuid, p_on boolean)
RETURNS boolean
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_was boolean;
BEGIN
  SELECT tracks_batches INTO v_was FROM catalog_items WHERE id = p_item AND tenant_id = p_tenant_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF v_was = p_on THEN
    RETURN true;
  END IF;
  IF p_on THEN  -- today's stock at each place becomes one "Opening stock" batch
    INSERT INTO stock_batches (tenant_id, catalog_item_id, variant_id, place_id, batch_no, quantity)
    SELECT l.tenant_id, l.catalog_item_id, l.variant_id, l.place_id, 'Opening stock', l.quantity
      FROM stock_levels l WHERE l.catalog_item_id = p_item AND l.tenant_id = p_tenant_id AND l.quantity > 0;
  ELSE
    -- closed, not deleted: old bills keep printing their batch no. and expiry
    UPDATE stock_batches SET status = 'closed' WHERE catalog_item_id = p_item AND tenant_id = p_tenant_id AND status = 'active';
  END IF;
  UPDATE catalog_items SET tracks_batches = p_on WHERE id = p_item AND tenant_id = p_tenant_id;
  RETURN true;
END $$;

-- Returns the credit (paise). Raises when the batch has no supplier or not that many.
CREATE OR REPLACE FUNCTION return_batch_to_supplier(
  p_tenant_id uuid, p_batch uuid, p_qty integer, p_user uuid, p_note text)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  b record;
  r record;
  v_amount bigint;
BEGIN
  SELECT * INTO b FROM stock_batches WHERE id = p_batch AND tenant_id = p_tenant_id AND status = 'active';
  IF NOT FOUND OR b.supplier_id IS NULL OR p_qty < 1 THEN
    RAISE EXCEPTION 'batch_return_bad' USING ERRCODE = 'P0001';
  END IF;
  PERFORM 1 FROM catalog_items WHERE id = b.catalog_item_id AND tenant_id = p_tenant_id FOR UPDATE;
  SELECT * INTO r FROM _stock_change(p_tenant_id, b.catalog_item_id, b.variant_id, -p_qty, 'supplier_return', NULL,
                                     p_note, p_user, NULL, NULL, p_batch, NULL, NULL);
  IF NOT r.ok THEN
    RAISE EXCEPTION 'batch_return_short' USING ERRCODE = 'P0001';
  END IF;
  -- what was paid: cost each plus the GST on that stock-in line (supplier bills include GST)
  v_amount := round(p_qty * COALESCE(b.cost_paise, 0)
                    * (1 + COALESCE((SELECT gst_rate FROM stock_in_lines WHERE id = b.stock_in_line_id), 0) / 100.0));
  INSERT INTO supplier_returns (tenant_id, supplier_id, batch_id, catalog_item_id, quantity, amount_paise, note, created_by)
  VALUES (p_tenant_id, b.supplier_id, p_batch, b.catalog_item_id, p_qty, v_amount, p_note, p_user);
  UPDATE stock_batches SET status = 'returned' WHERE id = p_batch AND quantity = 0;
  RETURN v_amount;
END $$;

REVOKE EXECUTE ON FUNCTION _stock_piece(uuid, uuid, uuid, uuid, uuid, integer, text, uuid, text, uuid, uuid) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION _stock_change(uuid, uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION _stock_move_line(uuid, uuid, uuid, uuid, integer, text, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb) TO service_role;
REVOKE EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb) TO service_role;
REVOKE EXECUTE ON FUNCTION send_stock_move(uuid, uuid, uuid, jsonb, text, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION send_stock_move(uuid, uuid, uuid, jsonb, text, uuid, text) TO service_role;
REVOKE EXECUTE ON FUNCTION finish_stock_move(uuid, uuid, boolean, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION finish_stock_move(uuid, uuid, boolean, uuid, text) TO service_role;
REVOKE EXECUTE ON FUNCTION set_batch_tracking(uuid, uuid, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION set_batch_tracking(uuid, uuid, boolean) TO service_role;
REVOKE EXECUTE ON FUNCTION return_batch_to_supplier(uuid, uuid, integer, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION return_batch_to_supplier(uuid, uuid, integer, uuid, text) TO service_role;
