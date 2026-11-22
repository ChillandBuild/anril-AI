-- Undo 315: every item goes back to the shop's advance rule, price always shared, no AI discounts.
ALTER TABLE catalog_items DROP COLUMN IF EXISTS ai_max_discount_pct;
ALTER TABLE catalog_items DROP COLUMN IF EXISTS ai_share_price;
ALTER TABLE catalog_items DROP COLUMN IF EXISTS advance_rule;
