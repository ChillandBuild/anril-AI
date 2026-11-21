-- Undo 304. Totals in catalog_items / catalog_item_variants are kept (they already hold the sums).
DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid);
DROP FUNCTION IF EXISTS _stock_level_add(uuid, uuid, uuid, uuid, integer);
DROP FUNCTION IF EXISTS default_stock_place(uuid);
-- Re-create the 204 / 294 versions of apply_stock_movement and apply_variant_stock_movement
-- from those migration files before running code older than 304.
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_reason_check;
DELETE FROM stock_movements WHERE reason IN ('transfer', 'count', 'write_off');
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_reason_check
  CHECK (reason IN ('sale', 'restock', 'adjustment', 'return'));
ALTER TABLE stock_movements DROP COLUMN IF EXISTS place_id;
DROP TABLE IF EXISTS stock_levels;
DROP TABLE IF EXISTS stock_places;
