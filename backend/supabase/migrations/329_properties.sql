-- 329: Real estate Properties + site visits (Batch P1).
-- A property is a catalogue item (item_type 'property') plus one row here with the real-estate details.
--   property_details   project, kind, BHK, price range, size, units total / left, map, RERA no, and the
--                      Bookings service ("Site visit") this property's visits are booked under.
--   property_unit_log  one row per (order, property): the units already taken off "units left" for that order,
--                      so a paid order counts once however many times the payment is reported.
--   property_visits    ties a Bookings booking to the property it is a visit for.
--   property_take_units(...)  the one atomic step "log the order + take the units off, never below 0".
-- Brochure = a shop file (catalog_files.catalog_item_id = the property); photos = catalog_media.
-- Nothing new is stored for those: they reuse the existing catalogue uploads.
--
-- item_type: no database constraint on catalog_items.item_type exists in migrations 136-325 (it is plain text),
-- so 'property' and 'course' (Batch P2) already fit. The block below only acts if the live database has a
-- CHECK on item_type that migrations do not show: it then replaces that check with a plain "not empty" check, so both fit.
--
-- All new tables: RLS on, no member policies - only the backend's service key reads or writes them.
-- Additive. Undo: undo/329_properties_undo.sql
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE c record; dropped boolean := false;
BEGIN
  FOR c IN
    SELECT con.conname
    FROM pg_constraint con
    WHERE con.conrelid = 'public.catalog_items'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ILIKE '%item_type%'
  LOOP
    EXECUTE format('ALTER TABLE public.catalog_items DROP CONSTRAINT %I', c.conname);
    dropped := true;
  END LOOP;
  IF dropped THEN
    ALTER TABLE public.catalog_items ADD CONSTRAINT catalog_items_item_type_known
      CHECK (length(btrim(item_type)) > 0);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.property_details (
  item_id          uuid PRIMARY KEY REFERENCES public.catalog_items(id) ON DELETE CASCADE,
  tenant_id        uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  project          text CHECK (project IS NULL OR length(project) <= 120),
  kind             text NOT NULL DEFAULT 'flat' CHECK (kind IN ('flat', 'villa', 'plot', 'commercial', 'other')),
  bhk              integer CHECK (bhk IS NULL OR bhk BETWEEN 1 AND 20),
  price_min_paise  bigint CHECK (price_min_paise IS NULL OR price_min_paise >= 0),
  price_max_paise  bigint CHECK (price_max_paise IS NULL OR price_max_paise >= 0),
  size_text        text CHECK (size_text IS NULL OR length(size_text) <= 80),
  units_total      integer CHECK (units_total IS NULL OR units_total >= 0),
  units_left       integer CHECK (units_left IS NULL OR units_left >= 0),
  map_url          text CHECK (map_url IS NULL OR length(map_url) <= 500),
  rera_no          text CHECK (rera_no IS NULL OR length(rera_no) <= 60),
  visit_service_id uuid REFERENCES public.booking_services(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (price_min_paise IS NULL OR price_max_paise IS NULL OR price_max_paise >= price_min_paise)
);
CREATE INDEX IF NOT EXISTS idx_property_details_tenant ON public.property_details (tenant_id);

CREATE TABLE IF NOT EXISTS public.property_unit_log (
  deal_id        uuid NOT NULL REFERENCES public.deals(id) ON DELETE CASCADE,
  item_id        uuid NOT NULL REFERENCES public.catalog_items(id) ON DELETE CASCADE,
  tenant_id      uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  qty            integer NOT NULL CHECK (qty > 0),
  taken          integer NOT NULL DEFAULT 0 CHECK (taken >= 0),
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (deal_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_property_unit_log_tenant ON public.property_unit_log (tenant_id);

CREATE TABLE IF NOT EXISTS public.property_visits (
  booking_id        uuid PRIMARY KEY REFERENCES public.bookings(id) ON DELETE CASCADE,
  property_item_id  uuid NOT NULL REFERENCES public.catalog_items(id) ON DELETE CASCADE,
  tenant_id         uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_property_visits_item ON public.property_visits (tenant_id, property_item_id);

ALTER TABLE public.property_details  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.property_unit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.property_visits   ENABLE ROW LEVEL SECURITY;

-- Log the order for this property and take the units off "units left" in one step. Returns how many units
-- were really taken (0 when this order was already counted, the property has no unit count, or none are left).
-- Two payment reports for the same order cannot both count: the (deal, property) row is the lock.
CREATE OR REPLACE FUNCTION public.property_take_units(p_tenant_id uuid, p_item_id uuid, p_deal_id uuid, p_qty integer)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_inserted integer;
  v_old integer;
  v_new integer;
BEGIN
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RETURN 0;
  END IF;
  INSERT INTO public.property_unit_log (deal_id, item_id, tenant_id, qty)
  VALUES (p_deal_id, p_item_id, p_tenant_id, p_qty)
  ON CONFLICT (deal_id, item_id) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  IF v_inserted = 0 THEN
    RETURN 0;
  END IF;
  SELECT units_left INTO v_old FROM public.property_details
   WHERE item_id = p_item_id AND tenant_id = p_tenant_id FOR UPDATE;
  IF v_old IS NULL THEN
    RETURN 0;
  END IF;
  v_new := GREATEST(v_old - p_qty, 0);
  UPDATE public.property_details SET units_left = v_new, updated_at = now()
   WHERE item_id = p_item_id AND tenant_id = p_tenant_id;
  UPDATE public.property_unit_log SET taken = v_old - v_new
   WHERE deal_id = p_deal_id AND item_id = p_item_id;
  RETURN v_old - v_new;
END;
$$;

REVOKE ALL ON FUNCTION public.property_take_units(uuid, uuid, uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.property_take_units(uuid, uuid, uuid, integer) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.property_take_units(uuid, uuid, uuid, integer) TO service_role;
