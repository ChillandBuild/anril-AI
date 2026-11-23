-- Undo 329: drop the property tables and function. Catalogue items with item_type 'property' stay (they are
-- ordinary catalogue rows); only the real-estate details, the per-order unit log and the visit links go.
DROP FUNCTION IF EXISTS public.property_take_units(uuid, uuid, uuid, integer);
DROP TABLE IF EXISTS public.property_visits;
DROP TABLE IF EXISTS public.property_unit_log;
DROP TABLE IF EXISTS public.property_details;
