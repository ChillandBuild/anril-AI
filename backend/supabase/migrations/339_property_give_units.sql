-- v9.2 #215 follow-up: a cancelled or fully refunded property order gives its units back to "units left".
-- property_take_units (migration 329) logged one row per (order, property) with the units it really took. Giving back
-- deletes that row and adds the same number back, capped at units_total, in one step: the DELETE is the lock, so two
-- cancels at once give back only once, and an order that is paid again later is counted again.
CREATE OR REPLACE FUNCTION public.property_give_units(p_tenant_id uuid, p_deal_id uuid)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  r record;
  v_total integer := 0;
BEGIN
  FOR r IN
    DELETE FROM public.property_unit_log
     WHERE deal_id = p_deal_id AND tenant_id = p_tenant_id
    RETURNING item_id, taken
  LOOP
    IF r.taken > 0 THEN
      UPDATE public.property_details
         SET units_left = CASE WHEN units_total IS NULL THEN units_left + r.taken
                               ELSE LEAST(units_left + r.taken, units_total) END,
             updated_at = now()
       WHERE item_id = r.item_id AND tenant_id = p_tenant_id AND units_left IS NOT NULL;
      v_total := v_total + r.taken;
    END IF;
  END LOOP;
  RETURN v_total;
END;
$$;

REVOKE ALL ON FUNCTION public.property_give_units(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.property_give_units(uuid, uuid) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.property_give_units(uuid, uuid) TO service_role;
