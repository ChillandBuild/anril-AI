-- Undo 307. Stock that came in through stock-ins stays (its movements are in stock_movements).
ALTER TABLE catalog_item_variants DROP COLUMN IF EXISTS cost_price_paise;
DROP TABLE IF EXISTS supplier_payments;
DROP TABLE IF EXISTS stock_in_lines;
DROP TABLE IF EXISTS stock_ins;
DROP TABLE IF EXISTS purchase_order_lines;
DROP TABLE IF EXISTS purchase_orders;
DROP FUNCTION IF EXISTS next_po_number(uuid);
DROP TABLE IF EXISTS purchase_counters;
DROP TABLE IF EXISTS suppliers;
