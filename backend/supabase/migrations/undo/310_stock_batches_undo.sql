-- Undo 310. Stock totals and stock per place are kept (batches only split them). Re-create the 309
-- versions of apply_stock_movement, apply_variant_stock_movement, _stock_move_line, send_stock_move and
-- finish_stock_move from 309_stock_moves.sql after running this.
DROP FUNCTION IF EXISTS return_batch_to_supplier(uuid, uuid, integer, uuid, text);
DROP FUNCTION IF EXISTS set_batch_tracking(uuid, uuid, boolean);
DROP FUNCTION IF EXISTS _stock_move_line(uuid, uuid, uuid, uuid, integer, text, uuid, uuid, jsonb);
DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb);
DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb);
DROP FUNCTION IF EXISTS _stock_change(uuid, uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid, uuid, uuid, jsonb);
DROP FUNCTION IF EXISTS _stock_piece(uuid, uuid, uuid, uuid, uuid, integer, text, uuid, text, uuid, uuid);
ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_reason_check;
UPDATE stock_movements SET reason = 'adjustment' WHERE reason = 'supplier_return';
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_reason_check
  CHECK (reason IN ('sale', 'restock', 'adjustment', 'return', 'transfer', 'count', 'write_off'));
ALTER TABLE stock_movements DROP COLUMN IF EXISTS batch_id;
DROP TABLE IF EXISTS supplier_returns;
DROP TABLE IF EXISTS deal_item_batches;
DROP TABLE IF EXISTS stock_batches;
ALTER TABLE stock_move_lines DROP COLUMN IF EXISTS batches;
ALTER TABLE deal_items DROP COLUMN IF EXISTS batch_id;
ALTER TABLE catalog_items DROP COLUMN IF EXISTS tracks_batches;
