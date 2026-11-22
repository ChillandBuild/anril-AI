-- Undo 312. Stock changes already made by finished counts stay (they are ordinary stock movements).
DROP FUNCTION IF EXISTS claim_stock_count(uuid, uuid, uuid, text);
DROP TABLE IF EXISTS stock_count_lines;
DROP TABLE IF EXISTS stock_counts;
