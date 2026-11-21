-- Undo 309. Stock that is on the way stays out of both places: receive or cancel open moves first.
DROP FUNCTION IF EXISTS finish_stock_move(uuid, uuid, boolean, uuid, text);
DROP FUNCTION IF EXISTS send_stock_move(uuid, uuid, uuid, jsonb, text, uuid, text);
DROP FUNCTION IF EXISTS _stock_move_line(uuid, uuid, uuid, uuid, integer, text, uuid);
DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid);
DROP FUNCTION IF EXISTS apply_stock_movement(uuid, uuid, integer, text, uuid, text, uuid, uuid, uuid);
-- Re-create the 304 versions of apply_stock_movement and apply_variant_stock_movement from that file.
DROP TABLE IF EXISTS stock_move_lines;
DROP TABLE IF EXISTS stock_moves;
ALTER TABLE stock_places DROP COLUMN IF EXISTS ready_note;
